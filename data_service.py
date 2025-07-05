# data_service.py
from abc import ABC, abstractmethod
import ast
import boto3
import pandas as pd
import os
import decimal
import json 

# Helper para convertir los tipos Decimal de DynamoDB a float para pandas
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            return float(o)
        return super(DecimalEncoder, self).default(o)

class DataService(ABC):
    @abstractmethod
    def get_processed_properties(self):
        pass

class DynamoDBService(DataService):
    def __init__(self):
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table('properties')
        # Cargar metadatos desde el archivo incluido en el paquete Lambda
        self._filters_metadata = self._load_metadata_from_file()
        self.pen_to_usd_rate = self._get_pen_to_usd_rate()

    def _load_metadata_from_file(self):
        script_dir = os.path.dirname(__file__)
        file_path = os.path.join(script_dir, 'diccionario_datos_scraping.txt')
        with open(file_path, 'r', encoding='utf-8') as f:
            return ast.literal_eval(f.read())

    def _get_pen_to_usd_rate(self):
        # ... (mismo código que la versión local)
        price_options = self._filters_metadata.get('Filter:price', {}).get('options', [])
        for currency in price_options:
            if currency.get('iso_code') == 'PEN':
                return currency.get('arbitraje', 3.7)
        return 3.7

    def _map_property_types(self, df):
        # ... (mismo código que la versión local)
        type_mapping = {
            opt['property_type_id']: opt['name']
            for opt in self._filters_metadata.get('Filter:propertyType', {}).get('options', [])
        }
        df['property_type_name'] = df['property_type_id'].map(type_mapping).fillna('No especificado')
        return df

    def _map_facilities(self, facility_ids):
        # ... (mismo código que la versión local)
        if not isinstance(facility_ids, list):
            return []
        facilities_mapping = {
            str(opt['id']): opt['nombre']
            for opt in self._filters_metadata.get('Filter:facilities', {}).get('options', [])
        }
        return [facilities_mapping.get(str(fid), 'Desconocido') for fid in facility_ids]

    def get_processed_properties(self):
        # Escanear toda la tabla de DynamoDB
        response = self.table.scan()
        items = response['Items']

        # DynamoDB puede paginar los resultados. Para un dataset grande, habría que iterar.
        while 'LastEvaluatedKey' in response:
            response = self.table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
            items.extend(response['Items'])

        properties_df = pd.DataFrame(items)
        if properties_df.empty:
            return pd.DataFrame() # Devolver DF vacío si no hay datos

        # --- Procesamiento idéntico al local ---
        properties_df['price_usd'] = properties_df.apply(
            lambda row: float(row['price']) / self.pen_to_usd_rate if row.get('currency_id') == 6 else float(row.get('price', 0)),
            axis=1
        )
        properties_df['price_per_m2_usd'] = properties_df.apply(
            lambda row: row['price_usd'] / float(row['m2']) if row.get('m2') and float(row['m2']) > 0 else 0,
            axis=1
        )
        properties_df = self._map_property_types(properties_df)
        properties_df['facilities_names'] = properties_df['facilities'].apply(self._map_facilities)

        return properties_df

def get_data_service():
    # En el entorno Lambda, siempre usaremos DynamoDB
    return DynamoDBService()