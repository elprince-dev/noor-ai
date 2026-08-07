#!/usr/bin/env node
import * as path from 'path';
import * as dotenv from 'dotenv';
// Load infra/.env so CDK_DEFAULT_ACCOUNT (and friends) can be set from a file.
// Does not override variables the CDK CLI already injected from AWS creds.
dotenv.config({ path: path.join(__dirname, '..', '.env') });

import * as cdk from 'aws-cdk-lib';
import { DataStack } from '../lib/data-stack';
import { ApiStack } from '../lib/api-stack';
import { WebStack } from '../lib/web-stack';
import { KnowledgeBaseStack } from '../lib/knowledge-base-stack';
import { APP_PREFIX } from '../lib/config';
import { DnsStack } from '../lib/dns-stack';
import { ObservabilityStack } from '../lib/observability-stack';

const DOMAIN_NAME = 'noorai.elprince.net';



const app = new cdk.App();

const env: cdk.Environment = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION || 'us-east-1',
};

// DNS + cert (us-east-1)
const dns = new DnsStack(app, `${APP_PREFIX}-Dns`, { env, domainName: DOMAIN_NAME });

// Persistence layer — owns long-lived data stores.
const data = new DataStack(app, `${APP_PREFIX}-Data`, { env });

const kb = new KnowledgeBaseStack(app, `${APP_PREFIX}-KnowledgeBase`, { env });

// Compute / API layer — depends on the data layer.
const api = new ApiStack(app, `${APP_PREFIX}-Api`, {
  env,
  chatTable: data.chatTable,
  tracesTable: data.tracesTable,
  feedbackTable: data.feedbackTable,
  knowledgeBaseId: kb.knowledgeBaseId,
});

// Observability layer — metric filters, dashboard, and alarm on the API logs.
new ObservabilityStack(app, `${APP_PREFIX}-Observability`, {
  env,
  apiLogGroup: api.apiLogGroup,
});

// Delivery layer — depends on the API layer.
// (Cross-stack references above make CDK order deploys automatically.)
new WebStack(app, `${APP_PREFIX}-Web`, {
  env,
  apiDomain: api.apiDomain,
  domainName: DOMAIN_NAME,
  hostedZone: dns.hostedZone,
  certificate: dns.certificate,
});
