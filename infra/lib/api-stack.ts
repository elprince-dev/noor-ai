import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import * as path from 'path';
import { pythonLambdaCode } from './python-lambda-code';
import { BEDROCK_MODEL_ID, BEDROCK_REGION, TRACE_RETENTION_DAYS } from './config';

export interface ApiStackProps extends cdk.StackProps {
  /** Chat history table provided by the DataStack. */
  readonly chatTable: dynamodb.ITable;
  /** Request trace table provided by the DataStack. */
  readonly tracesTable: dynamodb.ITable;
  /** User feedback table provided by the DataStack. */
  readonly feedbackTable: dynamodb.ITable;
  readonly knowledgeBaseId: string;
}

// AWS Lambda Web Adapter layer — runs the FastAPI app (uvicorn) inside the
// managed Python runtime and supports response streaming. No Docker needed.
// https://github.com/awslabs/aws-lambda-web-adapter
const LWA_LAYER_VERSION = 28;

/**
 * Compute / API layer. Owns the request-handling Lambda (FastAPI via the Lambda
 * Web Adapter) and its IAM permissions, exposed through a streaming Function
 * URL. Stateless — safe to redeploy or replace without touching persisted data.
 */
export class ApiStack extends cdk.Stack {
  /** Function URL domain (no scheme/path), consumed by the WebStack origin. */
  public readonly apiDomain: string;

  /** API Lambda log group, consumed by the observability stack (metric filters). */
  public readonly apiLogGroup: logs.LogGroup;

  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);

    // ─── Lambda: FastAPI via Lambda Web Adapter ──────────────
    // Python deps are bundled on the host with `uv` (no Docker).
    // The LWA layer + run.sh start uvicorn; `response_stream` invoke mode makes
    // FastAPI StreamingResponse stream through the Function URL.
    const backendDir = path.join(__dirname, '..', '..', 'backend');

    this.apiLogGroup = new logs.LogGroup(this, 'ApiFunctionLogs', {
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const lwaLayer = lambda.LayerVersion.fromLayerVersionArn(
      this,
      'LambdaWebAdapter',
      `arn:aws:lambda:${this.region}:753240598075:layer:LambdaAdapterLayerX86:${LWA_LAYER_VERSION}`
    );

    const apiFunction = new lambda.Function(this, 'ApiFunction', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'run.sh', // LWA startup script (starts uvicorn)
      timeout: cdk.Duration.seconds(60),
      memorySize: 512,
      code: pythonLambdaCode(backendDir, ['src', 'run.sh']),
      layers: [lwaLayer],
      environment: {
        // Lambda Web Adapter configuration
        AWS_LAMBDA_EXEC_WRAPPER: '/opt/bootstrap',
        AWS_LWA_INVOKE_MODE: 'response_stream',
        AWS_LWA_READINESS_CHECK_PATH: '/api/health',
        PORT: '8000',
        // Application configuration
        CHAT_TABLE: props.chatTable.tableName,
        BEDROCK_MODEL_ID: BEDROCK_MODEL_ID,
        BEDROCK_REGION: BEDROCK_REGION,
        KNOWLEDGE_BASE_ID: props.knowledgeBaseId,
        // Observability / tracing configuration
        TRACE_TABLE: props.tracesTable.tableName,
        FEEDBACK_TABLE: props.feedbackTable.tableName,
        TRACE_ENABLED: 'true',
        TRACE_RETENTION_DAYS: TRACE_RETENTION_DAYS.toString(),
      },
      logGroup: this.apiLogGroup,
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

    // Retrieve permission
    apiFunction.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['bedrock:Retrieve'],
        resources: [
          `arn:aws:bedrock:${this.region}:${this.account}:knowledge-base/${props.knowledgeBaseId}`,
        ],
      })
    );

    // DynamoDB permissions (cross-stack grants → policy references the table ARNs)
    props.chatTable.grantReadWriteData(apiFunction);
    props.tracesTable.grantReadWriteData(apiFunction);
    props.feedbackTable.grantReadWriteData(apiFunction);

    // ─── Function URL (streaming) ────────────────────────────
    // Public (AuthType NONE) like the previous API Gateway; CloudFront fronts it.
    const fnUrl = apiFunction.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
      invokeMode: lambda.InvokeMode.RESPONSE_STREAM,
    });

    // fnUrl.url is "https://<id>.lambda-url.<region>.on.aws/" — CloudFront's
    // HttpOrigin needs just the host, so strip scheme and trailing slash.
    this.apiDomain = cdk.Fn.select(2, cdk.Fn.split('/', fnUrl.url));

    new cdk.CfnOutput(this, 'FunctionUrl', { value: fnUrl.url });
  }
}
