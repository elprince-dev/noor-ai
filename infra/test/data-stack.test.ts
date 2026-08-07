import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { DataStack } from '../lib/data-stack';
import { TRACE_TABLE_NAME, FEEDBACK_TABLE_NAME } from '../lib/config';

/**
 * CDK assertion tests for the observability tables added to the DataStack
 * (traces + feedback). Validates Requirements 3.6 and 10.6:
 * key schemas, attribute definitions, TTL, GSI, and on-demand billing.
 */
describe('DataStack observability tables', () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    const stack = new DataStack(app, 'TestDataStack');
    template = Template.fromStack(stack);
  });

  describe('traces table', () => {
    test('exists with RequestId string partition key and no sort key', () => {
      template.hasResourceProperties('AWS::DynamoDB::Table', {
        TableName: TRACE_TABLE_NAME,
        KeySchema: [{ AttributeName: 'RequestId', KeyType: 'HASH' }],
        AttributeDefinitions: [
          { AttributeName: 'RequestId', AttributeType: 'S' },
        ],
      });
    });

    test('uses PAY_PER_REQUEST billing', () => {
      template.hasResourceProperties('AWS::DynamoDB::Table', {
        TableName: TRACE_TABLE_NAME,
        BillingMode: 'PAY_PER_REQUEST',
      });
    });

    test('has TTL enabled on the ExpiresAt attribute', () => {
      template.hasResourceProperties('AWS::DynamoDB::Table', {
        TableName: TRACE_TABLE_NAME,
        TimeToLiveSpecification: {
          AttributeName: 'ExpiresAt',
          Enabled: true,
        },
      });
    });

    test('has no global secondary indexes', () => {
      template.hasResourceProperties('AWS::DynamoDB::Table', {
        TableName: TRACE_TABLE_NAME,
        GlobalSecondaryIndexes: Match.absent(),
      });
    });
  });

  describe('feedback table', () => {
    test('exists with RequestId string partition key and no sort key', () => {
      template.hasResourceProperties('AWS::DynamoDB::Table', {
        TableName: FEEDBACK_TABLE_NAME,
        KeySchema: [{ AttributeName: 'RequestId', KeyType: 'HASH' }],
        AttributeDefinitions: Match.arrayWith([
          { AttributeName: 'RequestId', AttributeType: 'S' },
          { AttributeName: 'Rating', AttributeType: 'S' },
          { AttributeName: 'FeedbackAt', AttributeType: 'S' },
        ]),
      });
    });

    test('uses PAY_PER_REQUEST billing', () => {
      template.hasResourceProperties('AWS::DynamoDB::Table', {
        TableName: FEEDBACK_TABLE_NAME,
        BillingMode: 'PAY_PER_REQUEST',
      });
    });

    test('has RatingIndex GSI with Rating partition key and FeedbackAt sort key', () => {
      template.hasResourceProperties('AWS::DynamoDB::Table', {
        TableName: FEEDBACK_TABLE_NAME,
        GlobalSecondaryIndexes: [
          {
            IndexName: 'RatingIndex',
            KeySchema: [
              { AttributeName: 'Rating', KeyType: 'HASH' },
              { AttributeName: 'FeedbackAt', KeyType: 'RANGE' },
            ],
          },
        ],
      });
    });

    test('has no TTL specification', () => {
      template.hasResourceProperties('AWS::DynamoDB::Table', {
        TableName: FEEDBACK_TABLE_NAME,
        TimeToLiveSpecification: Match.absent(),
      });
    });
  });
});
