# RKNN engine candidate - HOST fault injection, NOT deployed

11 October 2026. This is a real RKNN API call-path candidate, but NOT a complete
camera backend, a matching-SDK claim, a production release, or live PPE inference.
No board library/firmware/model was replaced. MCU outputs remain disabled.

## Implemented

- edge/luckfox/rknn_engine.{h,c}: explicit open/infer/close with RKNN
  init/query/create_mem/set_io_mem/run/destroy_mem/destroy calls.
- A fresh zero-initialized object opens once. Invalid/partial open leaves FAULT
  and caller must close. No speculative restart or replacement of a live engine.
- model_and_sdk_verified defaults false. Only caller verification of actual model
  hash, export/label/normalization manifest and SDK ABI may set it. A boolean alone
  is neither verification nor release permission. There is no accepted model here.
- One native NHWC byte input, 1 x H x W x 3; UINT8 conversion mode like the pinned
  RV1103 reference. Source is pre-letterboxed, upright RGB888 with tight rows.
  Runtime padded rows are cleared and copied individually; graph normalization,
  pixel conversion and hardware cache coherency still require target validation.
- Exactly three affine INT8 seven-class NCHW heads (36 channels). Logical AND
  native output attrs must agree and describe tightly packed buffers. Index,
  batch, type, dims, element/byte count, scale/zp and stride are checked against
  caller contract before allocations. NHWC/NC1HWC2/YOLOv8 or unknown packing FAIL.
  This restriction may refuse a valid model on real firmware: implement a tested
  repacking path if needed, do not relax shape checks or guess row stride.
- Requested tensor allocation budget <=4 MiB (caller can choose less). This is
  NOT total RSS, actual allocator reservation, model weights/internal memory,
  CMA, media buffers or proof Mini B has enough RAM.
- Strictly increasing camera frame ID, non-backward capture/clock values,
  requested blocking run timeout 1..1000 ms, freshness <=750 ms rechecked AFTER
  completion. Failed/late inference clears output and locks engine in FAULT.
  Pointer results are borrowed until next infer or close; decode immediately.
  Never convert an error into NO_PERSON or a repeated positive APD report.
- close attempts each owned memory handle once, in reverse order, then context.
  Repeated close never repeats destruction. Destroy errors persist as failure;
  SDK ownership-on-error is unknown, so this is NOT evidence of zero target leaks.

## SDK provenance and remaining ABI gate

Pinned aiRockchip rknpu2 SDK 1.4.0 reference header (commit
 aacd9d216a1119565c9d48c77f65162c225d4f9c) is kept as .h.txt ONLY under
 debug/build-preflight/sdk-native/. The HOST checker verifies SHA256 before
 copying it into a temporary include directory. Tests link mocks, NOT downloaded
 .so/reference files. Obtain licensing permission for SDK usage/distribution;
 reference header copyright restrictions remain intact.

sdk-reference-manifest.json records Git blob SHA1 and SHA256 for small official
Rockchip/Luckfox reference files. All downloaded reference library hashes differ
from the pulled board inventory (micro-runtime static string 1.4.1b9). This does
NOT prove ABI incompatibility and does NOT prove header compatibility. Do not
install a reference library to make hashes match. Board API version was not queried.

## Tests and limits

Native checker now includes test_rknn_engine.c against the pinned header:

- Every mocked init/query/allocation/bind failure, including partial handles.
- 27 wrong-version/tensor/native-packing/allocation metadata scenarios.
- Run failure, invalid IDs, timestamps, monotonic rollback, stale completion,
  exceeded time budget, invalid RGB size/timeout, duplicate frame rejection.
- Input row padding, decoder handoff (empty synthetic output only), gate refusal,
  reverse/once-only cleanup including SDK mock errors that consume handles.

Evidence: debug/native-tests-20261011-rknn-engine.log.
HOST success is NOT ARM/uClibc ABI, driver timeout enforcement, cache coherency,
physical buffer cleanup, actual inference completion, accuracy or thermal proof.

Still missing: trusted seven-class weights/dataset/evaluation, matching SDK and
Linux build environment, hardware API/version query, camera RK-MPI buffer capture
and ownership, resize/rotation/pixel implementation, visibility adapter, tracker
integration, bounded supervisor on target, latency/RAM/CMA checks, MCU commissioning
and acceptance soak in actual enclosure. Never deploy this candidate by itself.
