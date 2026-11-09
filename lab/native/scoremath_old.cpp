// Deliberate backwards-incompatible native library: score_native is absent.
extern "C" int score_legacy(int amount) { return amount * 4; }
