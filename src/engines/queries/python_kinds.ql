import python

from string kind, string name, string file, int start_line
where
  (
    kind = "Class" and
    exists(Class c |
      name = c.getQualifiedName() and
      file = c.getLocation().getFile().getRelativePath() and
      start_line = c.getLocation().getStartLine()
    )
  )
  or
  (
    kind = "Function" and
    exists(Function f |
      not f.getScope() instanceof Class and
      name = f.getQualifiedName() and
      file = f.getLocation().getFile().getRelativePath() and
      start_line = f.getLocation().getStartLine()
    )
  )
  or
  (
    kind = "Method" and
    exists(Function f |
      f.getScope() instanceof Class and
      name = f.getQualifiedName() and
      file = f.getLocation().getFile().getRelativePath() and
      start_line = f.getLocation().getStartLine()
    )
  )
select name, kind, file, start_line
