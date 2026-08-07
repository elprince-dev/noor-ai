import * as cdk from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as cloudwatchActions from 'aws-cdk-lib/aws-cloudwatch-actions';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as subscriptions from 'aws-cdk-lib/aws-sns-subscriptions';
import { Construct } from 'constructs';
import { ERROR_RATE_PERIOD_MINUTES, ERROR_RATE_THRESHOLD_PCT } from './config';

export interface ObservabilityStackProps extends cdk.StackProps {
  /** API Lambda log group (trace JSON lines), provided by the ApiStack. */
  readonly apiLogGroup: logs.ILogGroup;
}

/** CloudWatch custom-metric namespace for trace-derived metrics. */
const TRACE_METRIC_NAMESPACE = 'NoorAi/Traces';

/**
 * Observability layer. Derives operational metrics from the structured trace
 * log lines emitted by the API Lambda (`log_type: "trace"`): metric filters
 * feed an error-rate alarm, and a dashboard combines metric widgets with
 * Logs Insights queries over the raw trace fields (Requirement 10).
 */
export class ObservabilityStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: ObservabilityStackProps) {
    super(scope, id, props);

    const period = cdk.Duration.minutes(ERROR_RATE_PERIOD_MINUTES);

    // ─── Metric filters on the trace log lines ───────────────
    // Every trace line counts as one request.
    new logs.MetricFilter(this, 'RequestCountFilter', {
      logGroup: props.apiLogGroup,
      metricNamespace: TRACE_METRIC_NAMESPACE,
      metricName: 'RequestCount',
      filterPattern: logs.FilterPattern.literal('{ $.log_type = "trace" }'),
      metricValue: '1',
    });

    // A trace with a failure object has $.failure.step set (null on success).
    new logs.MetricFilter(this, 'ErrorCountFilter', {
      logGroup: props.apiLogGroup,
      metricNamespace: TRACE_METRIC_NAMESPACE,
      metricName: 'ErrorCount',
      filterPattern: logs.FilterPattern.literal(
        '{ $.log_type = "trace" && $.failure.step = "*" }'
      ),
      metricValue: '1',
    });

    // Bedrock throttling surfaces as a ThrottlingException in failure.error.
    new logs.MetricFilter(this, 'ThrottleCountFilter', {
      logGroup: props.apiLogGroup,
      metricNamespace: TRACE_METRIC_NAMESPACE,
      metricName: 'ThrottleCount',
      filterPattern: logs.FilterPattern.literal(
        '{ $.log_type = "trace" && $.failure.error = "*ThrottlingException*" }'
      ),
      metricValue: '1',
    });

    // ─── Metrics and error-rate math ─────────────────────────
    const requests = new cloudwatch.Metric({
      namespace: TRACE_METRIC_NAMESPACE,
      metricName: 'RequestCount',
      statistic: 'Sum',
      period,
    });

    const errors = new cloudwatch.Metric({
      namespace: TRACE_METRIC_NAMESPACE,
      metricName: 'ErrorCount',
      statistic: 'Sum',
      period,
    });

    const throttles = new cloudwatch.Metric({
      namespace: TRACE_METRIC_NAMESPACE,
      metricName: 'ThrottleCount',
      statistic: 'Sum',
      period,
      label: 'Throttling errors',
    });

    const errorRate = new cloudwatch.MathExpression({
      expression: '100 * errors / requests',
      usingMetrics: { errors, requests },
      period,
      label: 'Error rate (%)',
    });

    // ─── Dashboard ───────────────────────────────────────────
    const logGroupNames = [props.apiLogGroup.logGroupName];

    const dashboard = new cloudwatch.Dashboard(this, 'TracesDashboard', {
      dashboardName: 'NoorAi-Traces',
    });

    dashboard.addWidgets(
      // Req 10.1 — total request latency percentiles.
      new cloudwatch.LogQueryWidget({
        title: 'Latency percentiles (ms)',
        logGroupNames,
        view: cloudwatch.LogQueryVisualizationType.LINE,
        queryString: [
          'filter log_type = "trace"',
          'stats pct(total_latency_ms, 50) as p50, pct(total_latency_ms, 90) as p90, pct(total_latency_ms, 99) as p99 by bin(5m)',
        ].join(' | '),
        width: 12,
        height: 6,
      }),
      // Req 10.2 — time-to-first-token percentiles.
      new cloudwatch.LogQueryWidget({
        title: 'TTFT percentiles (ms)',
        logGroupNames,
        view: cloudwatch.LogQueryVisualizationType.LINE,
        queryString: [
          'filter log_type = "trace"',
          'stats pct(ttft_ms, 50) as p50, pct(ttft_ms, 90) as p90, pct(ttft_ms, 99) as p99 by bin(5m)',
        ].join(' | '),
        width: 12,
        height: 6,
      })
    );

    dashboard.addWidgets(
      // Req 10.3 — error rate as a percentage of requests.
      new cloudwatch.GraphWidget({
        title: 'Error rate (%)',
        left: [errorRate],
        width: 12,
        height: 6,
      }),
      // Req 10.4 — Bedrock throttling errors per period.
      new cloudwatch.GraphWidget({
        title: 'Throttling errors',
        left: [throttles],
        width: 12,
        height: 6,
      })
    );

    dashboard.addWidgets(
      // Req 10.5 — estimated cost per UTC calendar day (computed costs only).
      new cloudwatch.LogQueryWidget({
        title: 'Estimated cost per day (USD)',
        logGroupNames,
        view: cloudwatch.LogQueryVisualizationType.BAR,
        queryString: [
          'filter log_type = "trace" and cost.computed',
          'stats sum(cost.usd) as daily_cost_usd by datefloor(@timestamp, 1d)',
        ].join(' | '),
        width: 24,
        height: 6,
      })
    );

    // ─── Error-rate alarm (Req 10.7, 10.8) ───────────────────
    // Missing data (zero traffic) must not breach.
    const alarm = errorRate.createAlarm(this, 'ErrorRateAlarm', {
      alarmDescription:
        `Trace error rate above ${ERROR_RATE_THRESHOLD_PCT}% over ` +
        `${ERROR_RATE_PERIOD_MINUTES} minutes`,
      threshold: ERROR_RATE_THRESHOLD_PCT,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    // Optional email notification — only when ALARM_EMAIL is configured
    // (loaded from infra/.env by the bin entry via dotenv).
    const alarmEmail = process.env.ALARM_EMAIL;
    if (alarmEmail) {
      const alarmTopic = new sns.Topic(this, 'AlarmTopic', {
        displayName: 'NoorAi error-rate alarm',
      });
      alarmTopic.addSubscription(new subscriptions.EmailSubscription(alarmEmail));
      alarm.addAlarmAction(new cloudwatchActions.SnsAction(alarmTopic));
    }

    new cdk.CfnOutput(this, 'DashboardName', { value: dashboard.dashboardName });
  }
}
