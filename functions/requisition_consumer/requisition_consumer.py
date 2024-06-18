from aws_lambda_powertools.utilities import parameters
from aws_lambda_powertools import Logger
from datetime import datetime, timedelta
from boto3.dynamodb.conditions import Key
from aws_lambda_powertools.shared.json_encoder import Encoder
import boto3
import os


class s3Exception(Exception):
    pass

class DynamoQueryException(Exception):
    pass


class ApptLookaheadException(Exception):
    pass


class NoApptRecordFoundException(Exception):
    pass


class DynamoUpdateException(Exception):
    pass

# environment variables
logger = Logger(log_uncaught_exceptions=True)

dynamodb_resource = boto3.resource('dynamodb')
bhc_requisitions = dynamodb_resource.Table('BHC_REQUISITIONS')

def update_item(item, table):
    update_expression = 'SET '
    expression_attribute_values = {}
    # generate update expressions
    for key in item:
        if key in ['partition_key', 'sort_key']:
            continue  # skip keys
        update_expression += f'{key}=:{key}, '
        expression_attribute_values[f':{key}'] = item.get(key)
    # remove trailing comma and white space
    update_expression = update_expression[:-2]

    try:
        table.update_item(
            Key={
                'partition_key': item.get('partition_key'),
                'sort_key': item.get('sort_key')
            },
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_attribute_values
        )
    except Exception as e:
        logger.error(e)
        raise DynamoUpdateException(e)


def lambda_handler(event, context):
    if event.get('event_type') == 'Scheduled':
        pass

    return
