# ROADMAP -- resolume-sync-visuals

## In Progress

## Ready

- [ ] Fix the 2 skipped tests in test_cli.py (test_tracked_test_output, test_mp4_validation) so they run in CI without real generated files
- [ ] Add CI pipeline (GitHub Actions for pytest with venv setup)
- [ ] Add Docker health check endpoint
- [ ] Add progress tracking API for long-running video generation jobs
- [ ] Add batch generation mode (process multiple songs in parallel)
- [ ] Add generation cost tracking and reporting per song
- [ ] Add webhook notifications when generation completes
- [ ] Add support for custom prompt templates per genre
- [ ] Add video quality validation (check for black frames, encoding artifacts)
- [ ] Add automatic retry for failed video model API calls
- [ ] Add gallery/preview page to web dashboard for generated visuals
- [ ] Add A/B testing for prompt variations to optimize visual quality

## Done
