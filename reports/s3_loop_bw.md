# Loop bandwidths, per modulation - 5 Sep

**Anvith.** Regenerate with `python reports/s3_loop_bw_study.py`. Both loops ran at one global bandwidth for every linear scheme until today; this is the sweep that replaces them, or declines to.

**The grid below measures a SINGLE-SPEED carrier loop, which is what `costas_loop` was when the sweep ran.** Its most useful result was not a bandwidth: it was that 16-QAM handed a residual offset of 0.02 x Rs - one `lockcheck.CARRIER_OFFSET_LIMIT` explicitly permits - decoded **1 of 28** files at every bandwidth that did not also cost clean files. That is an acquisition problem, not a tracking one, and `gardner_sync` had already solved the same problem years of convention earlier by gear-shifting. `costas_loop` now does too (`carrier.ACQ_SYMBOLS`, 4x for 150 symbols, both numbers measured), and with it the same 16-QAM cell reads **9/28 on the impaired arm with the clean arm unchanged at 14/28**. Re-running this study now would measure the gear-shifted loop; the tables below are kept as the single-speed measurement that motivated it, which is the honest before-column and the one the next sweep should be read against.

Confirmed across all four schemes after the change, same two arms, single-speed count in brackets:

| scheme | bw | clean | offset |
|---|---|---|---|
| bpsk | 0.02 | 28/28 (28) | 28/28 (28) |
| qpsk | 0.02 | 28/28 (28) | 28/28 (28) |
| 8psk | 0.02 | 21/28 (21) | 20/28 (18) |
| **8psk** | **0.04** | 21/28 (21) | **21/28** (21) |
| **16qam** | **0.02** | **14/28** (14) | **9/28** (1) |
| 16qam | 0.04 | 13/28 (13) | 13/28 (11) |

Each cell is `decodes/files` over 4 SNR points (4, 8, 10, 13 dB) x 7 seeds. The incumbent value is **bold**; the value this study chooses is marked `<-`. FSK is not here: its plug-in is a non-coherent tone bank with neither loop in it.

## The carrier loop

Impaired arm: `offset` - a residual carrier offset of 0.02 x Rs, left for the loop to remove.

| scheme | arm | 0.005 | 0.01 | 0.02 | 0.04 | 0.08 | picked |
|---|---|---|---|---|---|---|---|
| bpsk | clean | 28/28 | 28/28 | **28/28** `<-` | 28/28 | 28/28 | **0.02** |
| bpsk | offset | 28/28 | 28/28 | **28/28** `<-` | 28/28 | 28/28 |  |
| qpsk | clean | 28/28 | 28/28 | **28/28** `<-` | 28/28 | 24/28 | **0.02** |
| qpsk | offset | 0/28 | 28/28 | **28/28** `<-` | 28/28 | 24/28 |  |
| 8psk | clean | 21/28 | 21/28 | 21/28 | **21/28** `<-` | 13/28 | **0.04** |
| 8psk | offset | 0/28 | 0/28 | 18/28 | **21/28** `<-` | 13/28 |  |
| 16qam | clean | 14/28 | 14/28 | **14/28** | 13/28 `<-` | 7/28 | **0.04** |
| 16qam | offset | 0/28 | 0/28 | **1/28** | 11/28 `<-` | 7/28 |  |

Changes this sweep asks for:

- **16qam**: 0.02 -> 0.04

## The timing loop

Impaired arm: `phase` - the record started 2 samples late - half a symbol at this corpus's 4 samples per symbol - left for the loop to find.

| scheme | arm | 0.001 | 0.002 | 0.004 | 0.008 | 0.016 | picked |
|---|---|---|---|---|---|---|---|
| bpsk | clean | 22/28 | 28/28 | **28/28** `<-` | 27/28 | 27/28 | **0.004** |
| bpsk | phase | 28/28 | 28/28 | **28/28** `<-` | 28/28 | 26/28 |  |
| qpsk | clean | 26/28 | 28/28 | **28/28** `<-` | 28/28 | 28/28 | **0.004** |
| qpsk | phase | 28/28 | 28/28 | **28/28** `<-` | 28/28 | 28/28 |  |
| 8psk | clean | 20/28 | 21/28 | **21/28** `<-` | 20/28 | 21/28 | **0.004** |
| 8psk | phase | 20/28 | 21/28 | **21/28** `<-` | 20/28 | 21/28 |  |
| 16qam | clean | 12/28 | 14/28 `<-` | **13/28** | 14/28 | 13/28 | **0.002** |
| 16qam | phase | 14/28 | 14/28 `<-` | **13/28** | 14/28 | 13/28 |  |

Changes this sweep asks for:

- **16qam**: 0.004 -> 0.002

