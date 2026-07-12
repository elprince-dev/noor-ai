import * as cdk from 'aws-cdk-lib';
import * as route53 from 'aws-cdk-lib/aws-route53';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';
import { Construct } from 'constructs';

export interface DnsStackProps extends cdk.StackProps {
  /** The subdomain to host, e.g. "noorai.elprince.net". */
  readonly domainName: string;
}

/**
 * DNS + TLS layer. Owns a Route 53 hosted zone for the noorai subdomain
 * (delegated from elprince.net via a one-time NS record at the registrar)
 * and the ACM certificate CloudFront uses. Must live in us-east-1 because
 * CloudFront only accepts certificates from that region.
 */
export class DnsStack extends cdk.Stack {
  public readonly hostedZone: route53.IHostedZone;
  public readonly certificate: acm.ICertificate;

  constructor(scope: Construct, id: string, props: DnsStackProps) {
    super(scope, id, props);

    // Hosted zone for the SUBDOMAIN only. elprince.net stays at the registrar;
    // a one-time NS record there delegates this subdomain to these nameservers.
    this.hostedZone = new route53.PublicHostedZone(this, 'HostedZone', {
      zoneName: props.domainName,
    });

    // DNS-validated cert. CDK writes the validation record into the hosted
    // zone automatically, so once delegation is live this validates hands-free.
    this.certificate = new acm.Certificate(this, 'Certificate', {
      domainName: props.domainName,
      validation: acm.CertificateValidation.fromDns(this.hostedZone),
    });

    // The 4 nameservers to copy into the registrar as an NS record for "noorai".
    new cdk.CfnOutput(this, 'NameServers', {
      value: cdk.Fn.join(', ', this.hostedZone.hostedZoneNameServers!),
      description: 'Add these as an NS record for the noorai subdomain at your registrar.',
    });
    new cdk.CfnOutput(this, 'CertificateArn', { value: this.certificate.certificateArn });
  }
}