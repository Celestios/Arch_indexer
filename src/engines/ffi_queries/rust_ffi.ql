import rust

from Function f, string name, string sig, string file
where
  f.hasAttribute("no_mangle") and
  f.getLinkage() = "C" and
  name = f.getName() and
  sig = f.getSignature().toString() and
  file = f.getLocation().getFile().getRelativePath()
select name, sig, file
