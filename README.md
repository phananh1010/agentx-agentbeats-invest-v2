Added invest images to the publish matrix so GitHub Actions now builds and pushes both services automatically: scenarios/invest/agent/Dockerfile and scenarios/invest/evaluator/Dockerfile are included in publish.yml.
To trigger: push to main or tag (e.g., v1.0.0). The workflow logs into GHCR with GITHUB_TOKEN, builds for linux/amd64, and publishes images ghcr.io/<repo>-invest-agent and ghcr.io/<repo>-invest-evaluator with latest and semver tags.


docker build --platform linux/amd64 -t ghcr.io/phananh1010/agentx-agentbeats-invest-v2-invest-agent:latest -f scenarios/invest/agent/Dockerfile .

docker build --platform linux/amd64 -t ghcr.io/phananh1010/agentx-agentbeats-invest-v2-invest-agent:latest -f scenarios/invest/evaluator/Dockerfile .