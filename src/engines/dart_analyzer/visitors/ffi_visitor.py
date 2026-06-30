from analyzer.dart_ast.visitor import RecursiveAstVisitor

class FfiVisitor(RecursiveAstVisitor):
    """
    Detects FFI patterns:
    - dart:ffi NativeFunction usage
    - DynamicLibrary.lookupFunction calls
    - @external annotations
    """

    def __init__(self):
        self.results = []

    def visit_method_invocation(self, node):
        # Detect lookupFunction calls
        if (node.method_name.name == 'lookupFunction' and
            node.target?.static_type?.name == 'DynamicLibrary'):

            # Extract native function name from first argument
            native_name = node.argument.arguments.first.toString().strip('"')

            self.results.append({
                'name': f"lookup_{native_name}",
                'symbol_id': self._get_symbol_id(node),
                'signature': node.static_type.toString(),
                'native_name': native_name,
                'type': 'lookup',
                'line': node.offset
            })
        super().visit_method_invocation(node)

    def visit_function_declaration(self, node):
        # Detect @external functions (Rust bridge pattern)
        for annotation in node.metadata:
            if annotation.name == 'external':
                self.results.append({
                    'name': node.name.name,
                    'symbol_id': self._get_symbol_id(node),
                    'signature': node.element.toString(),
                    'native_name': node.name.name,
                    'type': 'external',
                    'line': node.offset
                })
                break
        super().visit_function_declaration(node)

    def visit_type_annotation(self, node):
        # Detect NativeFunction type annotations
        if node.type?.name == 'NativeFunction':
            self.results.append({
                'name': node.toString(),
                'symbol_id': self._get_symbol_id(node),
                'signature': node.type.toString(),
                'native_name': '',
                'type': 'native_function',
                'line': node.offset
            })
        super().visit_type_annotation(node)

    def _get_symbol_id(self, node) -> str:
        """Generate SCIP-compatible symbol ID."""
        # Use analyzer's element model for accurate ID
        element = node.declaredElement or node.staticElement
        if element:
            return element.library.name + '::' + element.name
        return f"local::{node.offset}"
