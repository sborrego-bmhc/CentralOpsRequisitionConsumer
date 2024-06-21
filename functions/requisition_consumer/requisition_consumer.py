from aws_lambda_powertools.utilities import parameters
from aws_lambda_powertools import Logger
from datetime import datetime, timedelta
from boto3.dynamodb.conditions import Key, Attr
from aws_lambda_powertools.shared.json_encoder import Encoder
import boto3
import os

class DynamoUpdateException(Exception):
    pass

class InvalidTicketTypeException(Exception):
    pass

# environment variables
expiration_timestamp_offset = int(os.environ.get('expiration_timestamp_offset'))

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


def close_requisition(req, partition_key):
    update_item({
        'partition_key': partition_key,
        'sort_key': 'METADATA',
        'requisition_status': 'CLOSED'
    },
    bhc_requisitions)


def remove_consumption_date_attr(req, partition_key):
    bhc_requisitions.update_item(
        Key={
            'partition_key': partition_key,
            'sort_key': 'METADATA'
        },
        UpdateExpression='REMOVE consumption_date')


def handle_req_expiration(req):
    pass


def process_NP_ATTR_close_requisition(req, partition_key):
    consumption_date = int(req.get('consumption_date'))
    now = int(datetime.now().timestamp())

    ticket_type = req.get('ticket_type')
    sched_tag_value = req.get('ticket_scheduling_result_tag_value')
    ticket_status = req.get('ticket_status')
    if ticket_type == 'FOLLOW-UP':
        # TODO: ask gurminder to add follow_up_ticket_scheduling_result_tag_value and reschedule_ticket_scheduling_result_tag_value
        # TODO: get status tags from dynamodb rule
        sched_result_values = ['scheduled_follow_up', 'scheduled_before_ticket_follow_up', 'scheduled_by_contact_center']
    elif ticket_type == 'RESCHEDULE':
        # TODO: get status tags from dynamodb rule
        # TODO: see what's up with trailing underscores
        sched_result_values = ['sch_scheduled', 'scheduled_before_ticket', 'scheduled_by_contact_center_']
    else:
        # TODO: raise error or write error event?
        raise InvalidTicketTypeException(f'Invalid ticket_type: {ticket_type}')
    
    
    if now > consumption_date and sched_tag_value in sched_result_values:
        # successful ticket solve
        # write requisition closed event
        update_item({
        'partition_key': partition_key,
        'sort_key': f'{datetime.now()}#requisition_closed',
        'event_description': f'{ticket_type} ticket solved with {sched_tag_value} result'
        },
        bhc_requisitions)
        # close requisition
        close_requisition(req, partition_key)
        # delete consumption_date attr
        remove_consumption_date_attr(req, partition_key)
    elif now > consumption_date:
        # unsuccessful ticket solve
        update_item({
            'partition_key': partition_key,
            'sort_key': f'{datetime.now()}#unsuccessful_ticket_solve',
            'event_description': f'Ticket solved with unsuccessful scheduling result {sched_tag_value}'
        })
        remove_consumption_date_attr(req, partition_key)
    elif consumption_date + expiration_timestamp_offset < int(datetime.now().timestamp()):
        # expired requisition
        handle_req_expiration(req)
    else:
        # TODO: take some action here?
        pass


def lambda_handler(event, context):
    # query dynamo for consumption dates
    # TODO: add last evaluated key pagination
    response = bhc_requisitions.scan(IndexName='consumption_date-index')

    for req in response.get('Items'):
        partition_key = req.get('partition_key')
        if 'NP_COMPLETED_ATTRITION' in partition_key or 'NP_MISSED_ATTRITION' in partition_key:
            process_NP_ATTR_close_requisition(req, partition_key)
        # elif 'SOME_OTHER_REQ_TYPE' in partition_key:
        #     pass
       

    return
