"use client";

import type { RepoMap } from "@/lib/types";

export default function ContractsPane({ repoMap }: { repoMap: RepoMap | null }) {
  return (
    <section className="pane pane-right" aria-labelledby="contracts-pane-heading">
      <h2 id="contracts-pane-heading" className="pane-heading">
        Repository Contracts
      </h2>

      {!repoMap ? (
        <p className="empty-note">
          Index a repository to see its models, routes, telemetry, and ADRs.
        </p>
      ) : (
        <>
          <p className="score-strip">
            <span>{repoMap.models.length} models</span>
            <span>{repoMap.routes.length} routes</span>
            <span>{repoMap.telemetry.length} telemetry</span>
            <span>{repoMap.adrs.length} ADRs</span>
            <span>{repoMap.indexed_files.length} files indexed</span>
          </p>

          <h3 className="section-title">Models</h3>
          <ul className="contract-list">
            {repoMap.models.map((model) => (
              <li key={`${model.file_path}:${model.line}`}>
                <strong>{model.name}</strong>{" "}
                <code>
                  {model.file_path}:{model.line}
                </code>
                <ul className="field-list">
                  {model.fields.map((field) => (
                    <li key={field.name}>
                      <code>{field.name}</code>: {field.type_annotation}
                      {field.required ? "" : " (optional)"}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>

          <h3 className="section-title">Routes</h3>
          <ul className="contract-list">
            {repoMap.routes.map((route) => (
              <li key={`${route.file_path}:${route.line}`}>
                <span className="badge method">{route.method}</span>{" "}
                <strong>{route.path}</strong>{" "}
                <code>
                  {route.file_path}:{route.line}
                </code>
              </li>
            ))}
          </ul>

          <h3 className="section-title">Telemetry</h3>
          <ul className="contract-list">
            {repoMap.telemetry.map((event) => (
              <li key={`${event.file_path}:${event.line}`}>
                <strong>{event.event_name}</strong>{" "}
                <span className="badge">{event.source_kind}</span>{" "}
                <code>
                  {event.file_path}:{event.line}
                </code>
                {event.properties.length > 0 ? (
                  <span className="remediation">
                    props: {event.properties.join(", ")}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>

          <h3 className="section-title">ADRs</h3>
          <ul className="contract-list">
            {repoMap.adrs.map((adr) => (
              <li key={`${adr.file_path}:${adr.line}`}>
                <strong>{adr.adr_id}</strong> {adr.title}{" "}
                <span className="badge">{adr.status}</span>{" "}
                <code>
                  {adr.file_path}:{adr.line}
                </code>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
