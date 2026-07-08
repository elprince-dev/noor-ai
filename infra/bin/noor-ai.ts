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
import { APP_PREFIX } from '../lib/config';

const app = new cdk.App();

const env: cdk.Environment = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION || 'us-east-1',
};

// Persistence layer — owns long-lived data stores.
const data = new DataStack(app, `${APP_PREFIX}-Data`, { env });

// Compute / API layer — depends on the data layer.
const api = new ApiStack(app, `${APP_PREFIX}-Api`, {
  env,
  chatTable: data.chatTable,
});

// Delivery layer — depends on the API layer.
// (Cross-stack references above make CDK order deploys automatically.)
new WebStack(app, `${APP_PREFIX}-Web`, {
  env,
  apiDomain: api.apiDomain,
});
