# handler.py
import json
from data_service import get_data_service
import pandas as pd
from collections import Counter
import decimal

# Se inicializa el servicio una vez para que pueda ser reutilizado en ejecuciones "cálidas" de Lambda
data_service = get_data_service()

def get_dashboard_metrics(event, context):
    """
    Esta es la función principal que API Gateway llamará.
    Reemplaza la lógica de la ruta de Flask.
    """
    try:
        # 1. Obtener y procesar los datos desde nuestro servicio (que ahora usa DynamoDB)
        properties_df = data_service.get_processed_properties()
        
        # Si la tabla de DynamoDB está vacía, devolver una respuesta controlada.
        if properties_df.empty:
            return {
                "statusCode": 200,
                "headers": { "Access-Control-Allow-Origin": "*" },
                "body": json.dumps({"message": "No hay propiedades en la base de datos."})
            }

        # 2. Realizar todos los cálculos de análisis (lógica idéntica a la de app.py)
        
        # Métricas Generales
        total_properties = len(properties_df)
        avg_price_usd = properties_df['price_usd'].mean()
        avg_m2 = properties_df[properties_df['m2'] > 0]['m2'].mean()
        avg_price_per_m2_usd = properties_df[properties_df['price_per_m2_usd'] > 0]['price_per_m2_usd'].mean()

        # Manejar posibles valores NaN para que JSON no falle
        if pd.isna(avg_price_usd): avg_price_usd = 0
        if pd.isna(avg_m2): avg_m2 = 0
        if pd.isna(avg_price_per_m2_usd): avg_price_per_m2_usd = 0

        # Análisis por Distrito
        district_analysis = properties_df[properties_df['price_per_m2_usd'] > 0].groupby('neighborhood')['price_per_m2_usd'].mean().sort_values(ascending=False)
        top_expensive_districts = district_analysis.head(5).reset_index().to_dict(orient='records')
        top_affordable_districts = district_analysis.tail(5).sort_values(ascending=True).reset_index().to_dict(orient='records')
        
        # Análisis por Tipo de Propiedad
        prop_type_analysis_df = properties_df.groupby('property_type_name').agg(
            count=('id', 'count'),
            avg_price_usd=('price_usd', 'mean'),
            avg_m2=('m2', lambda x: x[x > 0].mean()),
            avg_price_per_m2_usd=('price_per_m2_usd', lambda x: x[x > 0].mean())
        ).reset_index()
        
        prop_type_analysis_df.fillna(0, inplace=True)
        prop_type_analysis = prop_type_analysis_df.sort_values(by='count', ascending=False).to_dict(orient='records')
        
        # Análisis de Facilities (Comodidades)
        all_facilities = [facility for sublist in properties_df['facilities_names'] for facility in sublist]
        top_facilities = Counter(all_facilities).most_common(10)
        
        # Correlación Precio vs. Características
        price_by_bedrooms = properties_df[properties_df['bedrooms'] > 0].groupby('bedrooms')['price_usd'].mean().reset_index().to_dict(orient='records')
        price_by_bathrooms = properties_df[properties_df['bathrooms'] > 0].groupby('bathrooms')['price_usd'].mean().reset_index().to_dict(orient='records')

        # 3. Ensamblar el diccionario de respuesta
        response_data = {
            'general_metrics': {
                'total_properties': int(total_properties), # Convertir a int nativo de Python
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

        # 4. Formatear la respuesta final para API Gateway
        return {
            "statusCode": 200,
            "headers": {
                # Estos encabezados son cruciales para que tu página en S3 pueda llamar a la API
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": True
            },
            "body": json.dumps(response_data, cls=DecimalEncoder) # Usamos el encoder para convertir Decimals de DynamoDB
        }

    except Exception as e:
        # Imprimir el error en los logs de CloudWatch para poder depurar
        print(f"Error en la ejecución de la Lambda: {e}")
        # Formatear una respuesta de error para API Gateway
        return {
            "statusCode": 500,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Credentials": True
            },
            "body": json.dumps({"error": f"Ocurrió un error en el servidor: {str(e)}"})
        }

# Este helper es necesario porque DynamoDB devuelve números como tipo Decimal,
# que json.dumps() no sabe manejar por defecto.
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            # Convertir a float o int dependiendo de si tiene decimales
            if o % 1 > 0:
                return float(o)
            else:
                return int(o)
        return super(DecimalEncoder, self).default(o)