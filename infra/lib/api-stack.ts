import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import * as path from 'path';
import { pythonLambdaCode } from './python-lambda-code';
import { BEDROCK_MODEL_ID, BEDROCK_REGION } from './config';

export interface ApiStackProps extends cdk.StackProps {
  /** Chat history table provided by the DataStack. */
  readonly chatTable: dynamodb.ITable;
}

/**
 * Compute / API layer. Owns the request-handling Lambda, its IAM permissions,
 * and the public API Gateway. Stateless — safe to redeploy or replace without
 * touching persisted data.
 */
export class ApiStack extends cdk.Stack {
  /** REST API, consumed by the WebStack for the /api/* CloudFront behavior. */
  public readonly api: apigateway.RestApi;

  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);

    // ─── Lambda: API Handler ─────────────────────────────────
    // Python deps are bundled on the host with `uv` (no Docker).
    // See ./python-lambda-code for the bundling details.
    const backendDir = path.join(__dirname, '..', '..', 'backend');

    const apiLogGroup = new logs.LogGroup(this, 'ApiFunctionLogs', {
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const apiFunction = new lambda.Function(this, 'ApiFunction', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'handler.handler',
      timeout: cdk.Duration.seconds(60),
      memorySize: 512,
      code: pythonLambdaCode(backendDir, ['src', 'handler.py']),
      environment: {
        CHAT_TABLE: props.chatTable.tableName,
        BEDROCK_MODEL_ID: BEDROCK_MODEL_ID,
        BEDROCK_REGION: BEDROCK_REGION,
      },
      logGroup: apiLogGroup,
    });

    // Bedrock permissions. Cross-region inference profiles route to the
    // underlying foundation models in multiple regions, so both the profile
    // resource and the foundation-model ARNs (any region) must be allowed.
    apiFunction.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
        resources: [
          'arn:aws:bedrock:*::foundation-model/anthropic.claude*',
          `arn:aws:bedrock:*:${this.account}:inference-profile/*.anthropic.claude*`,
        ],
      })
    );

    // DynamoDB permissions (cross-stack grant → policy references the table ARN)
    props.chatTable.grantReadWriteData(apiFunction);

    // ─── API Gateway ─────────────────────────────────────────
    this.api = new apigateway.RestApi(this, 'NoorAiApi', {
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

    // Routes are namespaced under /api to match the backend and CloudFront.
    const apiRoot = this.api.root.addResource('api');
    apiRoot.addResource('ask').addMethod('POST', lambdaIntegration);
    apiRoot.addResource('sessions').addMethod('POST', lambdaIntegration);
    apiRoot.addResource('health').addMethod('GET', lambdaIntegration);

    new cdk.CfnOutput(this, 'ApiUrl', { value: this.api.url });
  }
}
