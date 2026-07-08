import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import { Construct } from 'constructs';
import * as path from 'path';

export interface WebStackProps extends cdk.StackProps {
  /** Lambda Function URL domain (host only) provided by the ApiStack. */
  readonly apiDomain: string;
}

/**
 * Delivery layer. Owns the static site bucket and the CloudFront distribution
 * that serves the frontend and proxies /api/* to API Gateway (single origin,
 * no CORS). Depends on the ApiStack for the API origin.
 */
export class WebStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: WebStackProps) {
    super(scope, id, props);

    const { apiDomain } = props;

    // ─── S3: Static Assets ───────────────────────────────────
    const websiteBucket = new s3.Bucket(this, 'WebsiteBucket', {
      bucketName: `noor-ai-frontend-${this.account}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL, // CloudFront only
    });

    // ─── CloudFront Distribution ─────────────────────────────
    const distribution = new cloudfront.Distribution(this, 'Distribution', {
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(websiteBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
      },
      // Route /api/* to the Lambda Function URL. The backend serves the same
      // /api/* paths, so CloudFront forwards them as-is (no path rewriting).
      // Host header must NOT be forwarded — Function URLs reject a mismatched
      // Host — hence ALL_VIEWER_EXCEPT_HOST_HEADER.
      additionalBehaviors: {
        '/api/*': {
          origin: new origins.HttpOrigin(apiDomain),
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
        },
      },
      defaultRootObject: 'index.html',
      // Handle Next.js client-side routing (return index.html for 404s)
      errorResponses: [
        {
          httpStatus: 403,
          responseHttpStatus: 200,
          responsePagePath: '/index.html',
          ttl: cdk.Duration.minutes(5),
        },
        {
          httpStatus: 404,
          responseHttpStatus: 200,
          responsePagePath: '/index.html',
          ttl: cdk.Duration.minutes(5),
        },
      ],
    });

    // ─── Deploy Frontend to S3 ───────────────────────────────
    // Deploys the Next.js static export (output: 'export' in next.config.js).
    // Run: cd frontend && npm run build
    new s3deploy.BucketDeployment(this, 'DeployWebsite', {
      sources: [s3deploy.Source.asset(path.join(__dirname, '..', '..', 'frontend', 'out'))],
      destinationBucket: websiteBucket,
      distribution,
      distributionPaths: ['/*'], // Invalidate cache on deploy
    });

    new cdk.CfnOutput(this, 'WebsiteUrl', {
      value: `https://${distribution.distributionDomainName}`,
    });
    new cdk.CfnOutput(this, 'CloudFrontDistributionId', {
      value: distribution.distributionId,
    });
  }
}
