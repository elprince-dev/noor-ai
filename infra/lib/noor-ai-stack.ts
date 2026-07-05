import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import { PythonFunction } from '@aws-cdk/aws-lambda-python-alpha';
import { Construct } from 'constructs';

export class NoorAiStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ─── DynamoDB: Chat History ───────────────────────────────
    const chatTable = new dynamodb.Table(this, 'ChatHistory', {
      tableName: 'noor-ai-chat-history',
      partitionKey: { name: 'SessionId', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'MessageIndex', type: dynamodb.AttributeType.NUMBER },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      timeToLiveAttribute: 'TTL',
    });

    // ─── Lambda: API Handler ─────────────────────────────────
    // Note: PythonFunction uses pip internally. Before deploying, run:
    //   cd backend && uv export --no-hashes --no-dev > requirements.txt
    const apiFunction = new PythonFunction(this, 'ApiFunction', {
      entry: '../backend',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'handler',
      index: 'handler.py',
      timeout: cdk.Duration.seconds(60),
      memorySize: 512,
      environment: {
        CHAT_TABLE: chatTable.tableName,
        BEDROCK_MODEL_ID: 'anthropic.claude-3-5-sonnet-20241022-v2:0',
        BEDROCK_REGION: 'us-east-1',
      },
      logRetention: logs.RetentionDays.ONE_WEEK,
    });

    // Bedrock permissions
    apiFunction.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
        resources: ['arn:aws:bedrock:*::foundation-model/anthropic.claude*'],
      })
    );

    // DynamoDB permissions
    chatTable.grantReadWriteData(apiFunction);

    // ─── API Gateway ─────────────────────────────────────────
    const api = new apigateway.RestApi(this, 'NoorAiApi', {
      restApiName: 'Noor AI API',
      deployOptions: {
        stageName: 'prod',
        throttlingRateLimit: 50,
        throttlingBurstLimit: 100,
      },
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: apigateway.Cors.ALL_METHODS,
        allowHeaders: ['Content-Type', 'Authorization'],
      },
    });

    const lambdaIntegration = new apigateway.LambdaIntegration(apiFunction);

    api.root.addResource('ask').addMethod('POST', lambdaIntegration);
    api.root.addResource('sessions').addMethod('POST', lambdaIntegration);
    api.root.addResource('health').addMethod('GET', lambdaIntegration);

    // ─── Outputs ─────────────────────────────────────────────
    new cdk.CfnOutput(this, 'ApiUrl', { value: api.url });
    new cdk.CfnOutput(this, 'TableName', { value: chatTable.tableName });
  }
}
