from aws_lambda_powertools.utilities import parameters
from aws_lambda_powertools import Logger
from datetime import datetime, timedelta
from boto3.dynamodb.conditions import Key, Attr
from aws_lambda_powertools.shared.json_encoder import Encoder
import boto3
import os

class DynamoUpdateException(Exception):
    pass


class DynamoScanException(Exception):
    pass


class DynamoGetException(Exception):
    pass


class InvalidTicketTypeException(Exception):
    pass

# environment variables
np_attrition_expiration_timestamp_offset = int(os.environ.get('np_attrition_expiration_timestamp_offset'))

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


def close_requisition(partition_key):
    update_item({
        'partition_key': partition_key,
        'sort_key': 'METADATA',
        'requisition_status': 'CLOSED',
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
    # TODO: get requirements, implement
    return


def get_sched_result_tag_success_values(req_type):
    try:
        rule = bhc_requisitions.get_item(
            Key={
                'partition_key': 'RULE',
                'sort_key': f'{req_type}_SCHEDULING_RESULT_TAG_VALUES'
            })
    except Exception as e:
        logger.error(e)
        raise DynamoGetException

    return rule.get('Item').get('sched_result_tag_values')


def validate_NP_ATTR_close(req, partition_key, ticket_type):
    # system error checks
    if ticket_type == 'FOLLOW-UP':
        sched_result_title = req.get('ticket_scheduling_result_tag_title')
        sched_result_value = req.get('ticket_scheduling_result_tag_value')
        sched_result_values_list = get_sched_result_tag_success_values('NP_COMPLETED_ATTRITION')
    elif ticket_type == 'MISSED':
        sched_result_title = req.get('ticket_patient_scheduling_result_tag_title')
        sched_result_value = req.get('ticket_patient_scheduling_result_tag_value')
        sched_result_values_list = get_sched_result_tag_success_values('NP_MISSED_ATTRITION')
    else:
        event_description = f'Invalid ticket type encountered: {ticket_type}'
        logger.error(event_description)
        update_item({
            'partition_key': partition_key,
            'sort_key': f'{datetime.now().timestamp}#system_error',
            'event_description': event_description
        },
        bhc_requisitions)
        return False, sched_result_title
    
    # TODO: check other values? (ticket_status, etc.)
    # check null result value
    if sched_result_value in [None, '']:
        event_description = f'Invalid scheduling result: Value={sched_result_value} Title={sched_result_title}'
        logger.error(event_description)
        update_item({
            'partition_key': partition_key,
            'sort_key': f'{datetime.now().timestamp()}#system_error',
            'event_description': event_description
        },
        bhc_requisitions)

        return False, sched_result_title
    
    # check known result value
    if sched_result_value not in sched_result_values_list:
        event_description = f'Unknown scheduling result: Value={sched_result_value} Title={sched_result_title}'
        logger.error(event_description)
        update_item({
            'partition_key': partition_key,
            'sort_key': f'{datetime.now().timestamp()}#system_error',
            'event_description': event_description
        },
        bhc_requisitions)
        # still close the requisition

    return True, sched_result_title


def process_NP_ATTR_close_requisition(req, partition_key):
    consumption_date = int(req.get('consumption_date'))
    now = int(datetime.now().timestamp())

    ticket_type = req.get('ticket_type')
    ticket_status = req.get('ticket_status')

    if now > consumption_date:
        req_closeable, sched_result_title = validate_NP_ATTR_close(req, partition_key, ticket_type)

        if req_closeable:
            # write requisition closed event
            update_item({
            'partition_key': partition_key,
            'sort_key': f'{datetime.now()}#requisition_closed',
            'event_description': f'{ticket_type} ticket solved with result: {sched_result_title}'
            },
            bhc_requisitions)
            # close requisition
            close_requisition(partition_key)
            # delete consumption_date attr
            remove_consumption_date_attr(req, partition_key)
        else:
            # write requisition unclosable event
            update_item({
            'partition_key': partition_key,
            'sort_key': f'{datetime.now()}#requisition_unclosable',
            'event_description': f'{ticket_type} ticket not closed with result: {sched_result_title}'
            },
            bhc_requisitions)
            remove_consumption_date_attr(req, partition_key)
    elif now > consumption_date + np_attrition_expiration_timestamp_offset:
        # TODO: set requisition_opened value on req open for exppiration handling
        # expired requisition
        handle_req_expiration(req)
    else:
        # TODO: take some action here or fall through?
        return


def lambda_handler(event, context):
    # scan index for consumption dates
    requisitions = []
    try:
        response = bhc_requisitions.scan(IndexName='consumption_date-index')
        requisitions.extend(response.get('Items'))

        while 'LastEvaluatedKey' in response:
            response = bhc_requisitions.scan(
            IndexName='consumption_date-index',
            ExclusiveStartKey=response['LastEvaluatedKey']
            )
            requisitions.extend(response.get('Items'))
    except Exception as e:
        logger.error(e)
        raise DynamoScanException(e)


    for req in requisitions:
        partition_key = req.get('partition_key')
        if 'NP_COMPLETED_ATTRITION' in partition_key or 'NP_MISSED_ATTRITION' in partition_key:
            process_NP_ATTR_close_requisition(req, partition_key)
        # elif 'SOME_OTHER_REQ_TYPE' in partition_key:
        #     pass
       
    # TODO: verify that the very last action taken for every logic path is remove_cunsomption_date_attr() in case of dynamo fail
    return
