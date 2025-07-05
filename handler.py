# handler.py
import json
import decimal
import pandas as pd
import numpy as np
from collections import Counter
from data_service import get_data_service

# Se inicializa el servicio una vez para que pueda ser reutilizado en ejecuciones "cálidas" de Lambda
data_service = get_data_service()

# ... (El resto de la clase DecimalEncoder no cambia)
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            if o % 1 > 0:
                return float(o)
            else:
                return int(o)
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        return super(DecimalEncoder, self).default(o)

def get_dashboard_metrics(event, context):
    """
    Esta es la función principal que API Gateway llamará.
    Incluye lógica mejorada para filtrar outliers y asegurar la precisión de los datos.
    """
    try:
        # 1. Obtener y procesar los datos desde nuestro servicio (DynamoDB)
        properties_df = data_service.get_processed_properties()
        
        if properties_df.empty:
            return {
                "statusCode": 200,
                "headers": { "Access-Control-Allow-Origin": "*" },
                "body": json.dumps({"message": "No hay propiedades en la base de datos."})
            }

        # --- INICIO DE LA CORRECCIÓN ---
        # Se convierten explícitamente las columnas de Decimal a un tipo numérico
        # que pandas pueda utilizar para operaciones matemáticas. Esta es la solución al error.
        properties_df['m2'] = pd.to_numeric(properties_df['m2'], errors='coerce')
        properties_df['price_usd'] = pd.to_numeric(properties_df['price_usd'], errors='coerce')
        properties_df.dropna(subset=['m2', 'price_usd'], inplace=True) # Elimina filas si la conversión falló
        # --- FIN DE LA CORRECCIÓN ---


        # 2. Recalcular la columna 'price_per_m2_usd' para asegurar la precisión
        m2_for_calc = properties_df['m2'].replace(0, np.nan) 
        properties_df['price_per_m2_usd'] = properties_df['price_usd'] / m2_for_calc
        properties_df['price_per_m2_usd'].replace([np.inf, -np.inf], np.nan, inplace=True)
        properties_df['price_per_m2_usd'].fillna(0, inplace=True)
        
        # 3. Filtrado de Outliers
        min_m2 = 15
        min_price_per_m2 = 50
        max_price_per_m2 = 15000
        
        initial_count = len(properties_df)
        
        properties_df_filtered = properties_df[
            (properties_df['m2'] >= min_m2) &
            (properties_df['price_per_m2_usd'] >= min_price_per_m2) &
            (properties_df['price_per_m2_usd'] <= max_price_per_m2)
        ].copy()
        
        filtered_count = len(properties_df_filtered)
        print(f"Filtrado de outliers: Se pasó de {initial_count} a {filtered_count} propiedades.")
        
        # ... (El resto del archivo no cambia, todos los cálculos posteriores funcionarán correctamente)
        
        # 4. A partir de aquí, todos los cálculos de análisis usan el DataFrame filtrado

        # Métricas Generales
        total_properties = len(properties_df_filtered)
        avg_price_usd = properties_df_filtered['price_usd'].mean()
        avg_m2 = properties_df_filtered['m2'].mean()
        avg_price_per_m2_usd = properties_df_filtered['price_per_m2_usd'].mean()

        if pd.isna(avg_price_usd): avg_price_usd = 0
        if pd.isna(avg_m2): avg_m2 = 0
        if pd.isna(avg_price_per_m2_usd): avg_price_per_m2_usd = 0

        # Análisis por Distrito
        district_analysis = properties_df_filtered.groupby('neighborhood')['price_per_m2_usd'].mean().sort_values(ascending=False)
        top_expensive_districts = district_analysis.head(5).reset_index().to_dict(orient='records')
        top_affordable_districts = district_analysis.tail(5).sort_values(ascending=True).reset_index().to_dict(orient='records')
        
        # Análisis por Tipo de Propiedad
        prop_type_analysis_df = properties_df_filtered.groupby('property_type_name').agg(
            count=('id', 'count'),
            avg_price_usd=('price_usd', 'mean'),
            avg_m2=('m2', 'mean'),
            avg_price_per_m2_usd=('price_per_m2_usd', 'mean')
        ).reset_index()
        
        prop_type_analysis_df.fillna(0, inplace=True)
        prop_type_analysis = prop_type_analysis_df.sort_values(by='count', ascending=False).to_dict(orient='records')
        
        # Análisis de Facilities (Comodidades)
        all_facilities = [facility for sublist in properties_df_filtered['facilities_names'] for facility in sublist]
        top_facilities = Counter(all_facilities).most_common(10)
        
        # Correlación Precio vs. Características
        price_by_bedrooms = properties_df_filtered[properties_df_filtered['bedrooms'] > 0].groupby('bedrooms')['price_usd'].mean().reset_index().to_dict(orient='records')
        price_by_bathrooms = properties_df_filtered[properties_df_filtered['bathrooms'] > 0].groupby('bathrooms')['price_usd'].mean().reset_index().to_dict(orient='records')

        # 5. Ensamblar el diccionario de respuesta
        response_data = {
            'general_metrics': {
                'total_properties': int(total_properties),
                'average_price_usd': float(avg_price_usd),
                'average_m2': float(avg_m2),
                'average_price_per_m2_usd': float(avg_price_per_m2_usd)
            },
            'districts': {
                'top_expensive_by_m2': top_expensive_districts,
                'top_affordable_by_m2': top_affordable_districts
            },
            'property_type_analysis': prop_type_analysis,
            'facilities_analysis': [{'name': f[0], 'count': f[1]} for f in top_facilities],
            'price_feature_correlation': {
                'by_bedrooms': price_by_bedrooms,
                'by_bathrooms': price_by_bathrooms,
            }
        }

        # 6. Formatear la respuesta final para API Gateway
        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": True
            },
            "body": json.dumps(response_data, cls=DecimalEncoder)
        }

    except Exception as e:
        print(f"Error en la ejecución de la Lambda: {e}")
        return {
            "statusCode": 500,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": True
            },
            "body": json.dumps({"error": f"Ocurrió un error en el servidor: {str(e)}"})
        }