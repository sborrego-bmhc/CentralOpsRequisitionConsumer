from aws_lambda_powertools.utilities import parameters
from aws_lambda_powertools import Logger
from datetime import datetime, timedelta
from boto3.dynamodb.conditions import Key, Attr
from aws_lambda_powertools.shared.json_encoder import Encoder
import boto3
import os

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


def check_NP_ATTR_close_criteria():
    pass


def handle_req_expiration():
    pass


def lambda_handler(event, context):
    if event.get('event_type') == 'Scheduled': # placeholder
        # query dynamo for consumption dates
        # TODO: add last evaluated key pagination
        response = bhc_requisitions.scan(IndexName='consumption_date-index')
        for req in response.get('Items'):
            consumption_date = int(req.get('consumption_date'))
            now = int(datetime.now().timestamp())

            # "ticket_scheduling_result_tag_value": "scheduled_follow_up" 
            # TODO: get sched tag values
            # TODO: make rule for tag values

            # TODO: write event

            if now > consumption_date:

                # close requisition
                partition_key = req.get('partition_key')
                sort_key = 'METADATA'
                update_item({
                    'partition_key': partition_key,
                    'sort_key': sort_key,
                    'requisition_status': 'CLOSED'
                },
                bhc_requisitions)
                

                # delete consumption_date attr
                bhc_requisitions.update_item(
                    Key={
                        'partition_key': partition_key,
                        'sort_key': sort_key
                    },
                    UpdateExpression='REMOVE consumption_date'
                )

    return
