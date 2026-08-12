from __future__ import annotations

from pathlib import Path
import unittest

import yaml


class CloudFormationLoader(yaml.SafeLoader):
    pass


def _construct_cloudformation_tag(
    loader: CloudFormationLoader,
    tag_suffix: str,
    node: yaml.Node,
) -> object:
    if isinstance(node, yaml.ScalarNode):
        value: object = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    else:
        value = loader.construct_mapping(node)
    return {tag_suffix: value}


CloudFormationLoader.add_multi_constructor("!", _construct_cloudformation_tag)


class DeploymentContractTests(unittest.TestCase):
    def test_http_api_uses_jwt_by_default_and_limits_public_demo_surface(self) -> None:
        template_path = Path(__file__).parents[1] / "deployment" / "template.yaml"
        template = yaml.load(template_path.read_text(encoding="utf-8"), Loader=CloudFormationLoader)

        parameters = template["Parameters"]
        self.assertEqual(
            parameters["DatabaseParameterName"]["Default"],
            "/continuity-ledger/database-url",
        )
        self.assertEqual(parameters["JwtIssuer"]["AllowedPattern"], "^https://.+")
        self.assertEqual(parameters["JwtAudience"]["MinLength"], 1)

        resources = template["Resources"]
        api = resources["ContinuityLedgerApi"]["Properties"]
        auth = api["Auth"]
        self.assertEqual(auth["DefaultAuthorizer"], "ContinuityJwtAuthorizer")
        authorizer = auth["Authorizers"]["ContinuityJwtAuthorizer"]
        self.assertEqual(authorizer["IdentitySource"], "$request.header.Authorization")
        self.assertIn("JwtConfiguration", authorizer)

        events = resources["ContinuityLedgerFunction"]["Properties"]["Events"]
        function = resources["ContinuityLedgerFunction"]["Properties"]
        self.assertEqual(
            function["Environment"]["Variables"]["DATABASE_PARAMETER_NAME"],
            {"Ref": "DatabaseParameterName"},
        )
        self.assertNotIn("DATABASE_URL", function["Environment"]["Variables"])
        policy = function["Policies"][0]["Statement"][0]
        self.assertEqual(policy["Action"], ["ssm:GetParameter"])
        public_events = {"Health", "DemoHome", "DemoScenarios", "DemoSeed", "DemoRun"}
        for event_name in public_events:
            self.assertEqual(
                events[event_name]["Properties"]["Auth"]["Authorizer"],
                "NONE",
            )
        self.assertNotIn("Auth", events["Events"]["Properties"])
        self.assertNotIn("Auth", events["Search"]["Properties"])
        self.assertNotIn("Auth", events["AgentRun"]["Properties"])
        self.assertEqual(events["AgentRun"]["Properties"]["Path"], "/agent/run")
        self.assertEqual(events["DemoRun"]["Properties"]["Path"], "/demo/run")
        for event in events.values():
            self.assertEqual(event["Properties"]["ApiId"], {"Ref": "ContinuityLedgerApi"})


if __name__ == "__main__":
    unittest.main()
