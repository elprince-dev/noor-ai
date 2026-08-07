import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import * as logs from 'aws-cdk-lib/aws-logs';
import { ObservabilityStack } from '../lib/observability-stack';
import {
  ERROR_RATE_PERIOD_MINUTES,
  ERROR_RATE_THRESHOLD_PCT,
} from '../lib/config';

const TRACE_METRIC_NAMESPACE = 'NoorAi/Traces';
const PERIOD_SECONDS = ERROR_RATE_PERIOD_MINUTES * 60;

/**
 * Synthesizes the ObservabilityStack with a helper stack providing the
 * required API log group, and returns the assertion Template.
 */
function synthesize(): Template {
  const app = new cdk.App();
  const helperStack = new cdk.Stack(app, 'TestHelperStack');
  const apiLogGroup = new logs.LogGroup(helperStack, 'ApiLogGroup');
  const stack = new ObservabilityStack(app, 'TestObservabilityStack', {
    apiLogGroup,
  });
  return Template.fromStack(stack);
}

/**
 * CDK assertion tests for the ObservabilityStack (Requirements 10.1-10.8):
 * three trace metric filters, dashboard widgets for latency, TTFT, error
 * rate, throttling, and daily cost, the error-rate alarm configuration,
 * and the optional email notification via ALARM_EMAIL.
 */
describe('ObservabilityStack', () => {
  const originalAlarmEmail = process.env.ALARM_EMAIL;
  let template: Template;

  beforeAll(() => {
    // Default template synthesized without email notifications configured.
    delete process.env.ALARM_EMAIL;
    template = synthesize();
  });

  afterAll(() => {
    if (originalAlarmEmail === undefined) {
      delete process.env.ALARM_EMAIL;
    } else {
      process.env.ALARM_EMAIL = originalAlarmEmail;
    }
  });

  describe('metric filters', () => {
    test('creates exactly three metric filters', () => {
      template.resourceCountIs('AWS::Logs::MetricFilter', 3);
    });

    test('RequestCount filter matches every trace line', () => {
      template.hasResourceProperties('AWS::Logs::MetricFilter', {
        FilterPattern: '{ $.log_type = "trace" }',
        MetricTransformations: [
          Match.objectLike({
            MetricNamespace: TRACE_METRIC_NAMESPACE,
            MetricName: 'RequestCount',
            MetricValue: '1',
          }),
        ],
      });
    });

    test('ErrorCount filter matches traces with a failure step', () => {
      template.hasResourceProperties('AWS::Logs::MetricFilter', {
        FilterPattern: '{ $.log_type = "trace" && $.failure.step = "*" }',
        MetricTransformations: [
          Match.objectLike({
            MetricNamespace: TRACE_METRIC_NAMESPACE,
            MetricName: 'ErrorCount',
            MetricValue: '1',
          }),
        ],
      });
    });

    test('ThrottleCount filter matches ThrottlingException failures', () => {
      template.hasResourceProperties('AWS::Logs::MetricFilter', {
        FilterPattern:
          '{ $.log_type = "trace" && $.failure.error = "*ThrottlingException*" }',
        MetricTransformations: [
          Match.objectLike({
            MetricNamespace: TRACE_METRIC_NAMESPACE,
            MetricName: 'ThrottleCount',
            MetricValue: '1',
          }),
        ],
      });
    });
  });

  describe('dashboard', () => {
    let dashboardBody: string;

    beforeAll(() => {
      const dashboards = template.findResources('AWS::CloudWatch::Dashboard');
      const keys = Object.keys(dashboards);
      expect(keys).toHaveLength(1);
      // DashboardBody is a CFN Fn::Join over strings and references;
      // stringify it so we can assert on the embedded query strings.
      dashboardBody = JSON.stringify(dashboards[keys[0]].Properties.DashboardBody);
    });

    test('is named NoorAi-Traces', () => {
      template.hasResourceProperties('AWS::CloudWatch::Dashboard', {
        DashboardName: 'NoorAi-Traces',
      });
    });

    test('contains a latency percentiles widget (Req 10.1)', () => {
      expect(dashboardBody).toContain('total_latency_ms');
      expect(dashboardBody).toContain('Latency percentiles (ms)');
    });

    test('contains a TTFT percentiles widget (Req 10.2)', () => {
      expect(dashboardBody).toContain('ttft_ms');
      expect(dashboardBody).toContain('TTFT percentiles (ms)');
    });

    test('contains an error-rate widget with the metric-math expression (Req 10.3)', () => {
      expect(dashboardBody).toContain('100 * errors / requests');
      expect(dashboardBody).toContain('Error rate (%)');
    });

    test('contains a throttling widget (Req 10.4)', () => {
      expect(dashboardBody).toContain('ThrottleCount');
      expect(dashboardBody).toContain('Throttling errors');
    });

    test('contains a daily-cost widget (Req 10.5)', () => {
      expect(dashboardBody).toContain('cost.usd');
      expect(dashboardBody).toContain('Estimated cost per day (USD)');
    });
  });

  describe('error-rate alarm', () => {
    test('uses the error-rate metric-math expression', () => {
      template.hasResourceProperties('AWS::CloudWatch::Alarm', {
        Metrics: Match.arrayWith([
          Match.objectLike({ Expression: '100 * errors / requests' }),
        ]),
      });
    });

    test.each(['RequestCount', 'ErrorCount'])(
      'references %s over a 5-minute period',
      (metricName) => {
        template.hasResourceProperties('AWS::CloudWatch::Alarm', {
          Metrics: Match.arrayWith([
            Match.objectLike({
              MetricStat: Match.objectLike({
                Metric: Match.objectLike({
                  Namespace: TRACE_METRIC_NAMESPACE,
                  MetricName: metricName,
                }),
                Period: PERIOD_SECONDS,
                Stat: 'Sum',
              }),
            }),
          ]),
        });
      }
    );

    test('breaches above the 5% threshold and treats missing data as not breaching', () => {
      template.hasResourceProperties('AWS::CloudWatch::Alarm', {
        Threshold: ERROR_RATE_THRESHOLD_PCT,
        EvaluationPeriods: 1,
        ComparisonOperator: 'GreaterThanThreshold',
        TreatMissingData: 'notBreaching',
      });
    });

    test('has no SNS topic or alarm actions when ALARM_EMAIL is unset', () => {
      template.resourceCountIs('AWS::SNS::Topic', 0);
      template.hasResourceProperties('AWS::CloudWatch::Alarm', {
        AlarmActions: Match.absent(),
      });
    });
  });

  describe('email notifications (ALARM_EMAIL set)', () => {
    let emailTemplate: Template;

    beforeAll(() => {
      process.env.ALARM_EMAIL = 'oncall@example.com';
      emailTemplate = synthesize();
      delete process.env.ALARM_EMAIL;
    });

    test('creates an SNS topic with an email subscription', () => {
      emailTemplate.resourceCountIs('AWS::SNS::Topic', 1);
      emailTemplate.hasResourceProperties('AWS::SNS::Subscription', {
        Protocol: 'email',
        Endpoint: 'oncall@example.com',
      });
    });

    test('wires the topic as an alarm action', () => {
      emailTemplate.hasResourceProperties('AWS::CloudWatch::Alarm', {
        AlarmActions: [Match.objectLike({ Ref: Match.anyValue() })],
      });
    });
  });
});
