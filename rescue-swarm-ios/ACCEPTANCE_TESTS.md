# Native app acceptance checklist

All checks below are PLANNED, not passed. Python's 73 passing tests do not validate Swift.
Record device/OS/build, inputs/model hash, settings, timestamps and logs for each run.

| ID | Test | Pass condition | Owner / environment |
|---|---|---|---|
| A01 | Create/join with Internet disconnected but local Wi-Fi active | Two phones discover/join and exchange a fixture image/result | Mohamed / two phones |
| A02 | Deny network permission, then enable it | Clear blocked state; retry connects without reinstalling | Mohamed / phone |
| A03 | Transfer fragmented frames, corrupt checksum, oversized header | Valid frames parse; invalid data is rejected without accepting a result or hanging | Mohamed / Swift tests |
| A04 | Single, round robin, next available on identical mock tasks | All IDs complete once; round-robin ownership matches roster; faster eligible worker gets more work under next-available | Mohamed / Swift tests + devices |
| A05 | Disconnect worker mid-image | New attempt completes on remaining worker; no lost task | Mohamed / two phones, local worker allowed |
| A06 | Deliver duplicate result and old-attempt result | No second acceptance, sighting or metric increment | Mohamed / injected transport |
| A07 | Heartbeating stalled worker; then all workers absent | Task deadline still expires; bounded retries; explicit waiting/failure without endless spinner | Mohamed / injected clock |
| A08 | Pause/resume/stop while results arrive | Pause accepts in-flight results only; resume continues; stop cannot be undone by late callback | Mohamed / Swift tests |
| A09 | Background/lock a worker and then coordinator | No promise of indefinite processing; rejoin/reopen recovers state; no duplicate acceptance | Mohamed / phones |
| A10 | Terminate coordinator after saving some results; reopen | Accepted results survive, old attempts invalidated and unfinished work resumes explicitly | Mohamed / storage tests + phone |
| A11 | Real Core ML detection with rotated/resized fixtures | Documented tolerances against reference boxes; coordinates map to original raster; no synthetic output presented as real | Evi / Mac + phone |
| A12 | Empty image, decode failure, missing model | Distinct no-person success versus error; actionable UI; bounded retry | Evi / tests + phone |
| A13 | Known geometry and missing/wrong metadata | Location matches numerical reference tolerance; missing inputs never generate invented GPS | Aidan / tests |
| A14 | Review/confirm/dismiss candidate offline | Changes persist; original image and label remain visible; missing map tiles do not block review | Aidan + Mohamed / phone |
| A15 | Send candidate to configured TAK receiver, interrupt connection, retry | Actual marker inspected; stable event identity; delivery state does not overclaim acknowledgment | Aidan / actual TAK setup |
| A16 | Serious/critical thermal events and battery limit | Worker stops taking work per policy; UI explains pause; recovers without losing task identity | Mohamed / injected state then device validation |
| A17 | Pair wrong/unapproved peer or incompatible protocol | Connection cannot process session data; legitimate pair can reconnect | Mohamed / secure transport milestone |
| A18 | Import dataset exceeding memory; large individual file | File-backed processing remains bounded; oversized item is rejected clearly | Mohamed / phone |
| A19 | Large text, VoiceOver, empty/error/loading states | Main workflow stays navigable; essential state is not conveyed by color alone | All / simulator + phone |
| A20 | Local worker enabled vs disabled | Same correctness; record effect on coordinator response and sustained throughput | Mohamed / phone |

## Performance evidence gate

Use a fixed labeled image subset and fixed model/settings. Warm models first. Run
at least three repetitions per configuration, rotating order and recording thermal
state. Compare local-only, one remote worker, round robin and next-available. Report
mean/spread, per-worker counts, transfer bytes including retries, first-result latency
and sustained throughput. Define correctness matching before reporting time to first
correct detection. Run a sustained session to reveal heating; report duration and
battery change without claiming precise energy measurements from battery percentage.

Pass means reproducible measurements and explained outcomes, not a predetermined
speedup. Keep mock scheduling evidence separate from real inference and phone results.

## First implementation checkpoint

Create the Xcode app and shared Swift package, implement frame codec and role screens,
then transfer one fixture and mock result. Verify against Python on Windows and then
between two iPhones. Save evidence for A01/A03 before adding model and TAK dependencies.
