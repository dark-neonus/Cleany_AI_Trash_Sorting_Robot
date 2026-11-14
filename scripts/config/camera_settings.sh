# Hand-tuned on 2026-11-14 (screenshots were overexposed). Exposure times are in 100 us units:
# front 3.0 ms, wrist 9.0 ms (was 31 ms, which clipped 37% of the wrist image to white).
# scripts/tools/tune_cameras.sh regenerates this file by matching auto exposure, which is
# what produced the too-bright values; check screenshots after re-running it.
# Applied by configure_cameras in hardware.sh.
FRONT_CAMERA_CONTROLS="auto_exposure=1,exposure_time_absolute=30,gain=64,brightness=128,white_balance_automatic=0,white_balance_temperature=2500"
WRIST_CAMERA_CONTROLS="auto_exposure=1,exposure_time_absolute=90,gain=64,brightness=128,white_balance_automatic=0,white_balance_temperature=3000"
# Wrist white balance is fixed at 3000 K, its most neutral manual value (white keeps a visible
# green tint: R128 G163 B128). The camera has no red/blue gain controls and its temperature control
# never reaches neutral (swept 2000-7500 K in 10 K steps; 4000 K, the real light, is yellow).
# Lowering saturation would shrink the tint but dull real colours just as much, so it stays 128.
