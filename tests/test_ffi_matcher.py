from engines.ffi_extractor import FfiSurface
from engines.ffi_matcher import FfiMatcher, FfiMatch


def test_exact_name_match():
    dart = [FfiSurface("native_init", "(int) -> bool", "lib/ffi.dart", "dart")]
    rust = [FfiSurface("native_init", "fn(i32) -> bool", "src/lib.rs", "rust")]
    matcher = FfiMatcher()
    matches = matcher.match(dart, rust)
    assert len(matches) == 1
    assert matches[0].source_symbol == "dart::lib/ffi.dart::native_init"
    assert matches[0].target_symbol == "rust::src/lib.rs::native_init"
    assert matches[0].match_type == "name"
    assert matches[0].confidence == 0.8


def test_name_and_signature_match():
    dart = [FfiSurface("process", "(bytes) -> int", "lib/ffi.dart", "dart")]
    rust = [FfiSurface("process", "(bytes) -> int", "src/lib.rs", "rust")]
    matcher = FfiMatcher()
    matches = matcher.match(dart, rust)
    assert len(matches) == 1
    assert matches[0].match_type == "name+signature"
    assert matches[0].confidence == 1.0


def test_no_match_different_names():
    dart = [FfiSurface("init_dart", "() -> void", "lib/ffi.dart", "dart")]
    rust = [FfiSurface("init_rust", "() -> ()", "src/lib.rs", "rust")]
    matcher = FfiMatcher()
    matches = matcher.match(dart, rust)
    assert len(matches) == 0


def test_name_collision_disambiguated_by_signature():
    dart = [
        FfiSurface("process", "(bytes) -> int", "lib/ffi.dart", "dart"),
        FfiSurface("process", "(string) -> bool", "lib/strings.dart", "dart"),
    ]
    rust = [
        FfiSurface("process", "(bytes) -> int", "src/lib.rs", "rust"),
        FfiSurface("process", "(string) -> bool", "src/strings.rs", "rust"),
    ]
    matcher = FfiMatcher()
    matches = matcher.match(dart, rust)
    assert len(matches) == 2
    assert all(m.match_type == "name+signature" for m in matches)


def test_same_language_not_matched():
    rust1 = [FfiSurface("foo", "() -> ()", "src/a.rs", "rust")]
    rust2 = [FfiSurface("foo", "() -> ()", "src/b.rs", "rust")]
    matcher = FfiMatcher()
    matches = matcher.match(rust1, rust2)
    assert len(matches) == 0


def test_symbol_id_format():
    surface = FfiSurface("init", "() -> ()", "src/lib.rs", "rust")
    matcher = FfiMatcher()
    sid = matcher._symbol_id(surface)
    assert sid == "rust::src/lib.rs::init"
