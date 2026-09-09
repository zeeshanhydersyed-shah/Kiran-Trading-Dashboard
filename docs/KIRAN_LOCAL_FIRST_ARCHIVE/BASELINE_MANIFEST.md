# Kiran Local-First Migration -- Immutable Baseline Manifest (SEQ-1)

- **Generated:** 2026-09-09T22:05:59
- **Archive root:** `D:\KIRAN_ARCHIVE` (off-repo; C: is space-constrained)
- **Files:** 94 &nbsp;|&nbsp; **Total bytes:** 1,898,679,178
- **Authorization:** `KIRAN_LOCAL_FIRST_MIGRATION` Phase 1 / DR-program SEQ-1. Owner decision D7 (2026-09-09): *preservation only* -- no historical row is mutated, corrected, or re-scraped.
- **Machine-checkable copy:** `BASELINE_MANIFEST.sha256` (same directory).
- **Verify:** `python -m archive.archive_manifest verify` (re-hashes every file under the archive root and compares).

## Contents

| Group | What it is | Files | Bytes |
|---|---|---|---|
| `STORE_MANIFEST.json` | Per-table row counts / column lists / per-file hashes for the Parquet store | 1 | 10,387 |
| `backup_set` | Folded-in prior frozen artifacts: the DR-006 rehabilitation baseline and the 17-file BI source-preservation set | 21 | 969,487,591 |
| `baseline` | Whole-DB immutable point-in-time snapshot of live `psx_data.db` (all 53 tables) captured via the SQLite Online Backup API + its capture report | 4 | 882,932,767 |
| `bronze` | Raw OHLCV substrate as Parquet (`prices`, `index_prices`), partitioned by year -- source of truth for price | 44 | 21,533,415 |
| `silver` | CA-adjusted prices + universe as Parquet (`prices_adjusted`, `sectors`, `stock_metadata`), as-captured | 24 | 24,715,018 |

## Provenance of the folded-in members

- **`backup_set/dr006_rehabilitation_baseline/`** -- the DR program's frozen rehabilitation baseline, captured 2026-09-04 (elevated session). Canonical original remains at `C:\Users\Lenovo\ZH_Research_PSX\trading_edge_program\rehabilitation_baseline\`. Expected SHA-256 of the `.db`: `c03a393f44e4d3a73978784e8c47a0dc6729c2af8362377f7daee76859c9a8e0`. NOTE: the capture *report* in `loop_dr_006/` still reads 'STOPPED -- no baseline captured'; that report predates the successful elevated attempt and is stale.
- **`backup_set/bi_source_preservation_20260903/`** -- DR-003 Phase A BI application + data preservation set (17 files). Verified here against its own `PRESERVATION_MANIFEST.sha256` (17/17 match) before folding in. Canonical original at `...\trading_edge_program\loop_dr_003\bi_source_preservation_20260903\`.

## Full file list

### `STORE_MANIFEST.json`

```
757ea2792f64c4511cc8bac094068da2b2a0213b54bfddc1242e3735e66748ba  STORE_MANIFEST.json  (10,387 b)
```

### `backup_set`

```
1c8191110fc84b391f37479523505270a227f461bf9cae6c224250c92532ea1e  backup_set/bi_source_preservation_20260903/BI_PROVENANCE_NOTE.md  (8,741 b)
ec4b7edc5008bbaf5975f55806fb6ddacb860b691a14fdd1d27d867cf1fdb14d  backup_set/bi_source_preservation_20260903/PRESERVATION_MANIFEST.md  (12,358 b)
b6c72a542fae0beec801c721b3621530a7e66ba87cc996c7a81cbfc8977f8d89  backup_set/bi_source_preservation_20260903/PRESERVATION_MANIFEST.sha256  (1,500 b)
9fedfc01a3d28c1cdc87ddc9191c60c5cc3d5cdd5bcfc5e07888187f9950bbae  backup_set/bi_source_preservation_20260903/bi_app/DB_Definitions.sql  (2,408 b)
06bf4af99102538af9f1c2cfd5a5b45875901167dc38dd2d4b425a3ce76adecc  backup_set/bi_source_preservation_20260903/bi_app/StartApp.cmd  (9 b)
f3a5dd3f9d5aea52012d10d94a14f7cb7dd052fd92909153b07331fdfa8ec902  backup_set/bi_source_preservation_20260903/bi_app/StartDB.cmd  (46 b)
353cd9cbb7b8c5e3bcfcc223626a7a0df60497ac544a67ed65aa7a805f18f468  backup_set/bi_source_preservation_20260903/bi_app/index.html  (5,227 b)
10cc18ee7158c1d044b562f121d6601cad0c08d9407833a23ea7f9c989f8c9c7  backup_set/bi_source_preservation_20260903/bi_app/index.js  (982 b)
a5d141bb455e13cf77655f4c704c8253d44d0b9999439006112da9a96d1dafbc  backup_set/bi_source_preservation_20260903/bi_app/package-lock.json  (88,363 b)
c45e13ac286c8026af956825e415ccfeb9ff5b771912b80f3ffc64074a1d4c5a  backup_set/bi_source_preservation_20260903/bi_app/package.json  (566 b)
f984eee8900ad87867b35afea972fd090b39524ea709351930d9f1f6039ef066  backup_set/bi_source_preservation_20260903/bi_app/preload.js  (27,793 b)
5009496de621fa0592b8984699fd712bc3e0aa74dff111b3a883eedc3f33ed1a  backup_set/bi_source_preservation_20260903/bi_app/preload_bkp.js  (24,171 b)
bfd4b0f24079319ff929f43f0539d9c6abe52458d0667f170e4d3c3532b8923b  backup_set/bi_source_preservation_20260903/bi_app/window.js  (72 b)
843e23c3fafc48dbd0a5b5c465a76cd371f915dd280b23e281c7d2e3dea352e1  backup_set/bi_source_preservation_20260903/bi_postgres_dump_company_index_companies_20260904.sql  (43,608,306 b)
9fedfc01a3d28c1cdc87ddc9191c60c5cc3d5cdd5bcfc5e07888187f9950bbae  backup_set/bi_source_preservation_20260903/bi_schema_DB_Definitions.sql  (2,408 b)
37b55c4cee0e793d4c66500e6f143354191eb5f3a741462e2cf9e9f04b18ca80  backup_set/bi_source_preservation_20260903/companies.csv  (28,807 b)
be6fedbf0461c356c695a1aa91943bc9078517d220b9450e8bb6aba214fb98e0  backup_set/bi_source_preservation_20260903/company_history.csv  (43,467,817 b)
0533ab1ef312032f0c23c90af37e8020f4652de0d87a5d79224c09496f971bb0  backup_set/bi_source_preservation_20260903/export_commands.sql  (1,092 b)
1cbba8f94e7fec76f887416291142509584b9a4f816f63b68085d3da102a678a  backup_set/bi_source_preservation_20260903/index_history.csv  (108,162 b)
9a7a69aea9be7ef9e86127a8232ba936f2be5dc817622363d96f8a073bfc1887  backup_set/dr006_rehabilitation_baseline/DR_006_FROZEN_KIRAN_REHABILITATION_BASELINE_CAPTURE_REPORT.md  (16,971 b)
c03a393f44e4d3a73978784e8c47a0dc6729c2af8362377f7daee76859c9a8e0  backup_set/dr006_rehabilitation_baseline/psx_data_baseline_DR006_20260904_113353.db  (882,081,792 b)
```

### `baseline`

```
e6b30612f394a3c71e737b883bfe50cc7bf9a22a7cac6c18116a7c9d64aaff99  baseline/capture_report_20260909_215346.json  (3,103 b)
21cf2e7f72e8f372428791d38e87c13f943bae5e8f208ba417d733ae09ebb6e7  baseline/psx_data_baseline_KIRAN_LFM_P1_20260909_215346.db  (882,896,896 b)
fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb  baseline/psx_data_baseline_KIRAN_LFM_P1_20260909_215346.db-shm  (32,768 b)
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  baseline/psx_data_baseline_KIRAN_LFM_P1_20260909_215346.db-wal  (0 b)
```

### `bronze`

```
cf338aba1819f8ce213fc7a52839841a768fe0e313497c1bb6470149fb261449  bronze/index_prices/year=2005/data.parquet  (8,158 b)
3dcab04e50f43d2e3493eeb04861267cebf7493dea3e7fce9a2ca8452768d3c4  bronze/index_prices/year=2006/data.parquet  (7,912 b)
7a563bfed6b254913a735d9b50e4d781ca821e24808823190b588b035f9da860  bronze/index_prices/year=2007/data.parquet  (7,992 b)
829c2c7746b6a9ecc859fccfc0d245765833b1eae4e373b5a1800a2cc0867964  bronze/index_prices/year=2008/data.parquet  (12,578 b)
d696cd22b814df47c772a7fb918fe51e34c9633290fc3231e5465e23ba09b081  bronze/index_prices/year=2009/data.parquet  (18,201 b)
9c96fcd03fe3ff1d00278fb9c8b113e8309116391799c88c0956375a3964b7d6  bronze/index_prices/year=2010/data.parquet  (18,170 b)
805b9ee44e4e705a969362dcced45bfd7dbe9ff7c28cfd2f1ecb47ef5bb307c9  bronze/index_prices/year=2011/data.parquet  (19,515 b)
5b5b2d0bfff1fe2216f1285a509d1ae89bb6f733910eaa149425b34ceea0926d  bronze/index_prices/year=2012/data.parquet  (23,827 b)
37d5177e2f764b668678a7f855822bcfadcec8a0df92b916d3704f7036348e03  bronze/index_prices/year=2013/data.parquet  (23,787 b)
47e69f99dcb2382d70e8a24c56b2736f21e4a0d8710ff91512e2056bbab9306d  bronze/index_prices/year=2014/data.parquet  (22,927 b)
4a957455c44bb09fb4d512dc4bc86b0594031e43bffd943cf119e3158bb58a60  bronze/index_prices/year=2015/data.parquet  (24,389 b)
6b3792d819d851439882934675afa213f56d7dcb95f2f96c18faca647d6e0d01  bronze/index_prices/year=2016/data.parquet  (29,598 b)
29885bd149e2b495c4f97055cdbc837af65d96605f94e4eba0c1204a5f49fa01  bronze/index_prices/year=2017/data.parquet  (29,541 b)
0fb7783e7e5b097f2308985bbb1876f85df60ef0746cb90aceea3077f4e53786  bronze/index_prices/year=2018/data.parquet  (28,940 b)
d3d4c8505c29b4c490e26c840957f32c1adb5d3a884510b9348ea0629672a9a6  bronze/index_prices/year=2019/data.parquet  (29,993 b)
976853888b50a28dc4cc8c435940e9c205a41db60e816d06be7c144c5b173e59  bronze/index_prices/year=2020/data.parquet  (8,125 b)
76cd0b50e55cd6368fa6d564f93f65cd93f97777a86844eb37264e05c0571a4e  bronze/index_prices/year=2021/data.parquet  (7,915 b)
9c09322ea43f0ce0b8d7e3e92de7ecf311d5aaff35153a9fc958fbd02e75ba89  bronze/index_prices/year=2022/data.parquet  (7,839 b)
3fc15dbcfcb12e80fff4120f1f398c162dc208d4e175599b94bf56764e664790  bronze/index_prices/year=2023/data.parquet  (8,040 b)
7b95e337aee7d9d121bbd5b65945ac7322cdb8f4e318d8f84b26ae316946e7a2  bronze/index_prices/year=2024/data.parquet  (30,065 b)
7edf2e4599108b726d24a379c30eeecebefae096e4ac2d6efb2e9db1fd63f854  bronze/index_prices/year=2025/data.parquet  (30,481 b)
0c6c92944071b517cd7b3186b741c09c3bb6c401e71288ab6dfc7853fee00dea  bronze/index_prices/year=2026/data.parquet  (21,064 b)
3b72871f24367e384d7d28d7a5692978a5c088d1f3e3e88f776ce7f226aa2e3d  bronze/prices/year=2005/data.parquet  (699,646 b)
cb4550e1e57e77cdd7c2e077ed2d337ce570352ef2b94de5d38c2f9179918320  bronze/prices/year=2006/data.parquet  (706,969 b)
cd3e2e8c2349643cfc8641db556a33f545bcb94fcc45880a84919eeba358bdc3  bronze/prices/year=2007/data.parquet  (778,664 b)
ceaa1adcf5e5d2df69be4b56981f9e335c8cfd15f4f7ddb0baa959ea456aed28  bronze/prices/year=2008/data.parquet  (656,631 b)
3cdd7e4e69288eabc78e0b5715b6460d567a6faf72865992f2813a4bdb9e91e6  bronze/prices/year=2009/data.parquet  (920,979 b)
3e7ec3b3353a1fd61bcc214aedda1f34a7f9256e05953ac4862e117c6830ac77  bronze/prices/year=2010/data.parquet  (1,099,191 b)
1a4f349b9f1bab48aa903cf0828b08d9462a86edde4c6dced56f7b4db22b88c3  bronze/prices/year=2011/data.parquet  (994,232 b)
caa5f9105f337a9c578d29484fcde2f2f04d77e530dc6fc499d352d24a469cd0  bronze/prices/year=2012/data.parquet  (987,058 b)
7edbbb45fe3063fc929b1127852577cb55a7a993a2d7324fdfc4f64b1530ad6a  bronze/prices/year=2013/data.parquet  (897,026 b)
a4ad1218a1582a376238335a13805c201dcdcefe998b4395bd14090ccd6ac0ef  bronze/prices/year=2014/data.parquet  (999,215 b)
882cda50164b619887049f682086e55417700fc644e6a6c72dcdc4d38f5eccd7  bronze/prices/year=2015/data.parquet  (986,797 b)
4978fa66027f79dad7e325a038d0b7482cb796c8b196ef80782c43436f8e2a2e  bronze/prices/year=2016/data.parquet  (1,012,298 b)
42cb735e87b3db76a561826ec26f28290c89c24aea746f7bca647bfcb4256ece  bronze/prices/year=2017/data.parquet  (1,047,508 b)
16996d8a10f830c94858e8bd21f174691501f52922474337066f67111ae50874  bronze/prices/year=2018/data.parquet  (952,627 b)
0fbf98c891f747642be649fc00b80cbe2e49842a2c910d06214742d2f49e209a  bronze/prices/year=2019/data.parquet  (862,619 b)
d7451be091720e993721083e62551c76d7a5e210fe52f2f0fce0d795ff06e8de  bronze/prices/year=2020/data.parquet  (798,147 b)
7a0d591b515a7f9829b2d093e9f804a3cd09b926315038e1d435c7b3de403964  bronze/prices/year=2021/data.parquet  (850,698 b)
1351ddc71f54f96cb5c39af417c47dcaaed73a5378de8699e84425c03be0c146  bronze/prices/year=2022/data.parquet  (803,136 b)
975383f5c698dec266faa564734858b21b9e0a396ab7b453ef9b760a59141998  bronze/prices/year=2023/data.parquet  (801,787 b)
56201c8110b1174684a44399ac4961de9a48e562f7050ec0a6bcc6c9bc110674  bronze/prices/year=2024/data.parquet  (1,363,202 b)
4707f1bef8b47dc7d98b85d3e2f5f23db465f740d7ca33e1f60db67efd61df21  bronze/prices/year=2025/data.parquet  (1,687,322 b)
a3850f90337a5700f337371b15c85305ace0c98b92c6fa6c7f8ca7129d787d38  bronze/prices/year=2026/data.parquet  (1,208,606 b)
```

### `silver`

```
0d3f9c5399bda03c41ebd386b98ee3f5af0d1bbec7d5bddddf580545a4909c04  silver/prices_adjusted/year=2005/data.parquet  (983,555 b)
8a5c944a22c7b89372d3167e4d543818a451c1c22a9a034b696958f63df60246  silver/prices_adjusted/year=2006/data.parquet  (984,278 b)
6b7fef6ffd7d96bf540c0085f08e88e195ee14205cd51024e9d9150e1309e82c  silver/prices_adjusted/year=2007/data.parquet  (1,058,688 b)
4d83c6a05eb40f460fe106ef190418a95e6f4c45fcf5d7f827d76fb1a4272842  silver/prices_adjusted/year=2008/data.parquet  (860,445 b)
686bc6b6cd07f022bad6dfa776544a009b9a617003dc0cc65bedd6f49146c2a4  silver/prices_adjusted/year=2009/data.parquet  (1,170,193 b)
191b475ce2ce74ed1761a98c60ca4e0cda3cac7d544a7ca78af28244d2375905  silver/prices_adjusted/year=2010/data.parquet  (1,362,398 b)
98c7e78ea27031ed628b6b354ab7c1852c9ec03b245b86686172f07fbf07c7fc  silver/prices_adjusted/year=2011/data.parquet  (1,195,705 b)
5f8cedfc6f8400b9c3b19d7bfe411168ffd66a0afd45f623ceb74c6ab844a921  silver/prices_adjusted/year=2012/data.parquet  (1,188,094 b)
d201d9f80e916682dba70c8370c35581edf615595d53272b5243e9409380bbf2  silver/prices_adjusted/year=2013/data.parquet  (1,086,209 b)
7898461d8742c533fab1165bfd1b9d4edf9a1a50b7aa6281b2961b8575779305  silver/prices_adjusted/year=2014/data.parquet  (1,181,947 b)
a53499d70fb8903ec0cf37f7b54f31c08d574851c62b34bf055ce4c3c7655e3b  silver/prices_adjusted/year=2015/data.parquet  (1,169,918 b)
4a4b1133e6859231e7414069f9134b0ebd7a3d4a72d6622843bdea0eeceb8be4  silver/prices_adjusted/year=2016/data.parquet  (1,180,137 b)
d1274e9e308ec9459c1f7b4832a939a6c4677f860f318f712ba0a82180eeaf6b  silver/prices_adjusted/year=2017/data.parquet  (1,219,760 b)
78de8a6bf706a501c265eaef86c87146d4ee0b0e5f30fef58d8da088bb748db8  silver/prices_adjusted/year=2018/data.parquet  (1,108,203 b)
70745a8c359e7e68914ffc21d1901059a8d5352712bc65c084d57c2cba7660c9  silver/prices_adjusted/year=2019/data.parquet  (980,291 b)
7f0df1a33684292b0679f74e34030a7d1554b5498a3843cf55e0cdc849e484d7  silver/prices_adjusted/year=2020/data.parquet  (911,522 b)
fb5eb5e0b0b86e01ed7530bfc65da412563372a9893d4a9488a01a0c6676c730  silver/prices_adjusted/year=2021/data.parquet  (946,281 b)
493af376385a15443e977c0c41bdf2d755866b9487431d3e7cc874f4cbbac761  silver/prices_adjusted/year=2022/data.parquet  (881,878 b)
55928a055737f022e99145d66da69ed02937b49fac7aa544e58fea64f4009f14  silver/prices_adjusted/year=2023/data.parquet  (861,231 b)
6b409c2271bd5001c05b4751f167d1eb5402314e017ef74e5dbee83cce3ba2cb  silver/prices_adjusted/year=2024/data.parquet  (1,423,695 b)
97e7cbbae6a317f8409ec531a83abc4e20ab9f8b1d625d8c5c0ec0202aef7a04  silver/prices_adjusted/year=2025/data.parquet  (1,725,179 b)
099cece6c30379067da5681e2f388fd367953a8680c5ef33c44dd99a46b821bf  silver/prices_adjusted/year=2026/data.parquet  (1,222,024 b)
e93731c166e65c16aeeb4e864aba3fbe167cc2d729edd5a668b17668983845c0  silver/sectors/sectors.parquet  (4,435 b)
37c4b2abe657929c43693eb7af5bf095c869c9f043316f4e9f6498f3cb868325  silver/stock_metadata/stock_metadata.parquet  (8,952 b)
```

