// Renders the Noor AI architecture diagram to SVG with official AWS icons.
// Graphviz runs via WebAssembly (@viz-js/viz) — no system Graphviz needed.
//
// Regenerate:  cd docs/diagram && npm install && npm run render
import { instance } from "@viz-js/viz";
import { readFileSync, writeFileSync } from "node:fs";

const FONT = "Helvetica";
const TEXT = "#232F3E";   // AWS squid ink
const MUTED = "#5A6B7B";
const EDGE = "#7B8894";

const ICONS = [
  "users", "route-53", "certificate-manager", "cloudfront",
  "simple-storage-service-s3", "lambda", "bedrock", "dynamodb",
];

/**
 * AWS service node: icon on top, name strictly below (never overlapping),
 * optional muted detail lines under the name.
 */
function svc(id, icon, title, sub = []) {
  const subRows = sub
    .map(
      (s) =>
        `<TR><TD><FONT POINT-SIZE="10" COLOR="${MUTED}">${s}</FONT></TD></TR>`
    )
    .join("");
  return `  ${id} [shape=none, margin=0, label=<
    <TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="1">
      <TR><TD FIXEDSIZE="TRUE" WIDTH="66" HEIGHT="66"><IMG SRC="icons/${icon}.png" SCALE="TRUE"/></TD></TR>
      <TR><TD><FONT POINT-SIZE="12"><B>${title}</B></FONT></TD></TR>
      ${subRows}
    </TABLE>>]`;
}

const dot = `
digraph NoorAI {
  graph [
    rankdir=LR,
    splines=ortho,
    bgcolor="white",
    pad=0.5,
    nodesep=0.8,
    ranksep=1.1,
    fontname="${FONT}",
    fontsize=15,
    fontcolor="${TEXT}",
  ]
  node [fontname="${FONT}", fontcolor="${TEXT}"]
  edge [
    color="${EDGE}", arrowsize=0.8, penwidth=1.2,
    fontname="${FONT}", fontsize=10, fontcolor="${MUTED}",
  ]

  // ── Actors outside AWS ──────────────────────────────────────────────
${svc("user", "users", "User")}

  ingest [
    shape=box, style="rounded,dashed", penwidth=1.2, color="${EDGE}",
    margin="0.25,0.15", label=<
    <TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="1">
      <TR><TD><FONT POINT-SIZE="12"><B>Ingest pipeline (local)</B></FONT></TD></TR>
      <TR><TD><FONT POINT-SIZE="10" COLOR="${MUTED}">download_data.sh → build_corpus.py → sync.py</FONT></TD></TR>
      <TR><TD><FONT POINT-SIZE="10" COLOR="${MUTED}">Quran + Sahih al-Bukhari + Sahih Muslim, ~43k files</FONT></TD></TR>
    </TABLE>>]

  // ── AWS Cloud ───────────────────────────────────────────────────────
  subgraph cluster_aws {
    label="AWS Cloud  ·  us-east-1"
    labeljust=l
    style=rounded
    color="${TEXT}"
    penwidth=1.4
    margin=20

    subgraph cluster_edge {
      label="Edge &amp; Delivery"
      labeljust=l
      style="rounded,filled"
      fillcolor="#F2F7FB"
      color="#B9CDDD"
      fontsize=13
      margin=14

${svc("route53", "route-53", "Route 53", ["noorai.elprince.net"])}
${svc("acm", "certificate-manager", "Certificate Manager", ["TLS certificate"])}
${svc("cloudfront", "cloudfront", "CloudFront")}
${svc("s3web", "simple-storage-service-s3", "S3 static frontend", ["Next.js export"])}
    }

    subgraph cluster_api {
      label="Compute / API"
      labeljust=l
      style="rounded,filled"
      fillcolor="#FDF4EA"
      color="#E8CBA8"
      fontsize=13
      margin=14

${svc("lambda", "lambda", "Lambda · Function URL", ["FastAPI + LangChain", "response streaming"])}
    }

    subgraph cluster_ai {
      label="AI / RAG — Amazon Bedrock"
      labeljust=l
      style="rounded,filled"
      fillcolor="#EFF9F3"
      color="#AFD8BF"
      fontsize=13
      margin=14

${svc("claude", "bedrock", "Claude Haiku 4.5", ["inference profile"])}
${svc("kb", "bedrock", "Knowledge Base", ["Cohere Embed Multilingual v3"])}
${svc("s3vectors", "simple-storage-service-s3", "S3 Vectors index", ["1024-dim · cosine"])}
${svc("s3corpus", "simple-storage-service-s3", "S3 corpus bucket")}
    }

    subgraph cluster_data {
      label="Persistence"
      labeljust=l
      style="rounded,filled"
      fillcolor="#F6F2FA"
      color="#CBB8DD"
      fontsize=13
      margin=14

${svc("ddb", "dynamodb", "DynamoDB", ["chat history · TTL"])}
    }
  }

  // ── Request path (orthogonal edges; xlabel required with splines=ortho)
  user       -> cloudfront [xlabel="HTTPS"]
  route53    -> cloudfront [style=dashed, xlabel="alias"]
  acm        -> cloudfront [style=dashed, xlabel="TLS"]
  cloudfront -> s3web      [xlabel="/* static"]
  cloudfront -> lambda     [xlabel="/api/* stream"]

  lambda -> claude [xlabel="InvokeModel"]
  lambda -> kb     [xlabel="Retrieve"]
  lambda -> ddb    [xlabel="sessions"]

  kb -> s3vectors [xlabel="vectors"]

  // ── Ingestion path (offline) ────────────────────────────────────────
  ingest   -> s3corpus [style=dashed, xlabel="s3 sync"]
  s3corpus -> kb       [style=dashed, xlabel="ingestion job"]
}
`;

const viz = await instance();
let svg = viz.renderString(dot, {
  format: "svg",
  images: ICONS.map((n) => ({
    name: `icons/${n}.png`,
    width: "256px",
    height: "256px",
  })),
});

// Inline every icon as a base64 data URI so the SVG is self-contained.
for (const n of ICONS) {
  const b64 = readFileSync(`icons/${n}.png`).toString("base64");
  svg = svg.replaceAll(`icons/${n}.png`, `data:image/png;base64,${b64}`);
}

writeFileSync("../architecture.svg", svg);
console.log("docs/architecture.svg written,", (svg.length / 1024).toFixed(0), "KB");
