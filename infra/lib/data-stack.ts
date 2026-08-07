import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { Construct } from 'constructs';
import { CHAT_TABLE_NAME, TRACE_TABLE_NAME, FEEDBACK_TABLE_NAME } from './config';

/**
 * Persistence layer. Owns long-lived data stores (DynamoDB today; add future
 * tables, caches, or buckets here). Kept separate so data lifecycle is
 * decoupled from stateless compute and delivery layers.
 */
export class DataStack extends cdk.Stack {
  /** Chat history table, consumed by the API stack. */
  public readonly chatTable: dynamodb.Table;

  /** Request trace table (observability), consumed by the API stack. */
  public readonly tracesTable: dynamodb.Table;

  /** User feedback table, consumed by the API stack. */
  public readonly feedbackTable: dynamodb.Table;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    this.chatTable = new dynamodb.Table(this, 'ChatHistory', {
      tableName: CHAT_TABLE_NAME,
      partitionKey: { name: 'SessionId', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'MessageIndex', type: dynamodb.AttributeType.NUMBER },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      timeToLiveAttribute: 'TTL',
    });

    this.tracesTable = new dynamodb.Table(this, 'TracesTable', {
      tableName: TRACE_TABLE_NAME,
      partitionKey: { name: 'RequestId', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      timeToLiveAttribute: 'ExpiresAt',
    });

    this.feedbackTable = new dynamodb.Table(this, 'FeedbackTable', {
      tableName: FEEDBACK_TABLE_NAME,
      partitionKey: { name: 'RequestId', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    this.feedbackTable.addGlobalSecondaryIndex({
      indexName: 'RatingIndex',
      partitionKey: { name: 'Rating', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'FeedbackAt', type: dynamodb.AttributeType.STRING },
    });

    new cdk.CfnOutput(this, 'TableName', { value: this.chatTable.tableName });
    new cdk.CfnOutput(this, 'TracesTableName', { value: this.tracesTable.tableName });
    new cdk.CfnOutput(this, 'FeedbackTableName', { value: this.feedbackTable.tableName });
  }
}
