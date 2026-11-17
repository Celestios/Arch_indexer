; Tree-sitter query for Rust declarations
(struct_item
  name: (type_identifier) @struct.name) @struct.def

(enum_item
  name: (type_identifier) @enum.name) @enum.def

(trait_item
  name: (type_identifier) @trait.name) @trait.def

(function_item
  name: (identifier) @function.name) @function.def

(impl_item
  type: (type_identifier) @impl.type) @impl.def
