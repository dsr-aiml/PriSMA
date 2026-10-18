# PriSMA 0.8.6 verification

validation.json records automated checks and the exact-predecessor upgrade rehearsal. Tests and the supplied Canva evidence evaluation use local data and mocked queue/provider transports. No live provider calls or new collection were made. Actual Docker startup remains an installed-app check.

1. Finish active work, install using migration.md, rebuild services, and confirm `.prisma-version` prints 0.8.6. Verify the installed checksums with `python3 scripts/overlay.py --target "$PWD" --verify-installed`.
2. Open the original saved Canva assessment, choose Reanalyse, keep the XML sitemap selected and create the new assessment. It should queue successfully instead of returning “Service unavailable.” Check that its XML document, saved attribution and selected sources are retained.
3. Confirm the original report and prior Research conversations are still available. Reanalyse must produce a different report ID and use retained sources; Refresh remains a separate collection action.
4. Check that source selection and engine settings remain functional. Unsupported legacy source fields should receive a source-specific validation message with no document body in the error.
5. Existing 0.8.5 declaration inspection, Research depth, themes and landing animation should be unchanged. Their frontend implementation files are outside this hotfix payload.

The offline evaluation reproduced the previous source-contract failure, then exercised the actual Reanalyse HTTP endpoint with all 52 exported Canva sources: HTTP 202, one queued job, all sources cloned, XML accepted and the original report/settings unchanged.
