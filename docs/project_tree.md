# Project File Tree

```text
Arch_indexer/
└── src/
   ├── main.py
   ├── auditor/
   │   ├── analyzer.py
   │   ├── classifier.py
   │   ├── compiler.py
   │   ├── condition_registry.py
   │   ├── config_loader.py
   │   ├── edge_weights.py
   │   ├── field_validator.py
   │   ├── interfaces.py
   │   ├── path_tracer.py
   │   ├── propagation.py
   │   ├── registry.py
   │   ├── validator.py
   │   └── violation_checkers/
   │       ├── __init__.py
   │       ├── base.py
   │       ├── dependency.py
   │       ├── naming.py
   │       ├── pending.py
   │       └── structural.py
   ├── change_tracker/
   │   ├── git_coupling.py
   │   ├── invalidation.py
   │   ├── tracker.py
   │   └── watcher.py
   ├── commands/
   │   ├── __init__.py
   │   ├── analyze.py
   │   ├── audit.py
   │   ├── clear_pending.py
   │   ├── impact.py
   │   ├── init.py
   │   ├── mcp.py
   │   ├── registry.py
   │   ├── report.py
   │   ├── set_fields.py
   │   ├── set_status.py
   │   └── watch.py
   ├── db/
   │   ├── base.py
   │   ├── cascade.py
   │   ├── connection.py
   │   ├── interfaces.py
   │   ├── repository.py
   │   ├── repository_compliance.py
   │   ├── repository_edges.py
   │   ├── repository_files.py
   │   ├── repository_metrics.py
   │   ├── repository_symbols.py
   │   └── schema.sql
   ├── engines/
   │   ├── base.py
   │   ├── communities.py
   │   ├── edge_weights.py
   │   ├── ffi_linker.py
   │   ├── registry.py
   │   ├── scip_pb2.py
   │   ├── scip_wrapper.py
   │   ├── scip/
   │   │   ├── __init__.py
   │   │   ├── indexers.py
   │   │   ├── ingester.py
   │   │   ├── parser.py
   │   │   ├── utils.py
   │   │   └── wrapper.py
   │   └── treesitter/
   │       ├── __init__.py
   │       ├── annotations.py
   │       ├── control_flow.py
   │       ├── extractor.py
   │       ├── folding.py
   │       ├── loader.py
   │       ├── metrics.py
   │       ├── rules.py
   │       ├── types_extractor.py
   │       └── queries/
   │           ├── dart.scm
   │           ├── python.scm
   │           ├── rust.scm
   │           └── typescript.scm
   ├── interface/
   │   ├── formatters.py
   │   ├── server.py
   │   ├── server_config.py
   │   ├── validators.py
   │   └── tools/
   │       ├── __init__.py
   │       ├── audit.py
   │       ├── compile_context.py
   │       ├── context.py
   │       ├── impact.py
   │       └── lookup.py
   ├── interfaces/
   │   ├── __init__.py
   │   └── container.py
   ├── reporter/
   │   └── generator.py
   ├── setup/
   │   ├── initializer.py
   │   ├── mcp_config.py
   │   └── registry.py
   └── utils/
       ├── exclusions.py
       ├── helpers.py
       ├── session.py
       ├── single_instance.py
       └── violation_id.py
```
