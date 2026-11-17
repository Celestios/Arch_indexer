; Tree-sitter query for Dart declarations
(class_definition
  name: (identifier) @class.name) @class.def

(method_signature
  name: (identifier) @method.name) @method.def

(function_signature
  name: (identifier) @function.name) @function.def
