; Tree-sitter query for Python declarations
(class_definition
  name: (identifier) @class.name) @class.def

(function_definition
  name: (identifier) @function.name) @function.def

(call
  function: (identifier) @call.name) @call

(call
  function: (attribute
    attribute: (identifier) @call.method)) @call.attr
