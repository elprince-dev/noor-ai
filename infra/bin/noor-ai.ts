#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { NoorAiStack } from '../lib/noor-ai-stack';

const app = new cdk.App();

new NoorAiStack(app, 'NoorAI', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: 'us-east-1',
  },
});
