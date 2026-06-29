import dart

from Expr e, string name, string sig, string file
where
  (
    e instanceof FunctionAccessExpr and
    e.getPackage().getName() = "dart:ffi"
  )
  or
  (
    e instanceof MethodAccessExpr and
    e.getMethod().getName() = "lookupFunction" and
    e.getReceiver().getType().getName() = "DynamicLibrary"
  )
  or
  (
    e instanceof TypeAccessExpr and
    e.getType().getName() = "NativeFunction"
  )
select e.toString(), e.getType().toString(), e.getLocation().getFile().getRelativePath()
