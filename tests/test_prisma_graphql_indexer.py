from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from pmcursor.drift import check_spec_drift
from pmcursor.indexer import index_repository


def test_prisma_model_extraction(tmp_path: Path) -> None:
    schema = tmp_path / "prisma" / "schema.prisma"
    schema.parent.mkdir(parents=True)
    schema.write_text(
        dedent(
            """\
            datasource db {
              provider = "postgresql"
            }

            // User account model
            model User {
              id        Int      @id @default(autoincrement())
              email     String   @unique
              bio       String?
              posts     Post[]
              // inline comment ignored
              website   String?  @default("https://example.com")

              @@index([email])
              @@map("users")
            }
            """
        ),
        encoding="utf-8",
    )

    repo_map = index_repository(tmp_path)
    assert "prisma/schema.prisma" in repo_map.indexed_files
    assert len(repo_map.models) == 1

    user = repo_map.models[0]
    assert user.name == "User"
    assert user.file_path == "prisma/schema.prisma"
    assert user.line == 6
    assert user.base_classes == ["PrismaModel"]

    fields = {f.name: f for f in user.fields}
    assert set(fields) == {"id", "email", "bio", "posts", "website"}

    assert fields["id"].type_annotation == "Int"
    assert fields["id"].required is True
    assert fields["id"].line == 7

    assert fields["email"].type_annotation == "String"
    assert fields["email"].required is True
    assert fields["email"].line == 8

    assert fields["bio"].type_annotation == "String?"
    assert fields["bio"].required is False
    assert fields["bio"].line == 9

    assert fields["posts"].type_annotation == "Post[]"
    assert fields["posts"].required is True
    assert fields["posts"].line == 10

    assert fields["website"].type_annotation == "String?"
    assert fields["website"].required is False
    assert fields["website"].line == 12


def test_graphql_type_input_query_mutation_extraction(tmp_path: Path) -> None:
    schema_gql = tmp_path / "schema.graphql"
    schema_gql.write_text(
        dedent(
            """\
            # Core user type
            type User {
              id: ID!
              email: String! # primary email
              nickname: String
            }

            input OrderInput {
              userId: ID!
              note: String
            }

            type Query {
              getUser(id: ID!): User
              listUsers: [User!]!
            }

            type Mutation {
              createOrder(input: OrderInput!): Order!
            }
            """
        ),
        encoding="utf-8",
    )

    extra_gql = tmp_path / "orders.gql"
    extra_gql.write_text(
        dedent(
            """\
            type Order {
              id: ID!
              totalCents: Int!
            }
            """
        ),
        encoding="utf-8",
    )

    repo_map = index_repository(tmp_path)
    assert "schema.graphql" in repo_map.indexed_files
    assert "orders.gql" in repo_map.indexed_files

    models_by_name = {m.name: m for m in repo_map.models}
    assert set(models_by_name) == {"User", "OrderInput", "Order"}

    user = models_by_name["User"]
    assert user.base_classes == ["GraphQLType"]
    assert user.line == 2
    user_fields = {f.name: f for f in user.fields}
    assert user_fields["id"].required is True
    assert user_fields["id"].type_annotation == "ID!"
    assert user_fields["email"].type_annotation == "String!"
    assert user_fields["nickname"].required is False
    assert user_fields["nickname"].type_annotation == "String"

    order_input = models_by_name["OrderInput"]
    assert order_input.base_classes == ["GraphQLInput"]
    assert order_input.line == 8
    input_fields = {f.name: f for f in order_input.fields}
    assert input_fields["userId"].required is True
    assert input_fields["note"].required is False

    routes_by_fn = {r.function_name: r for r in repo_map.routes}
    assert set(routes_by_fn) == {"getUser", "listUsers", "createOrder"}

    get_user = routes_by_fn["getUser"]
    assert get_user.method == "QUERY"
    assert get_user.path == "/getUser"
    assert get_user.request_model == "ID"
    assert get_user.response_model == "User"
    assert get_user.line == 14

    list_users = routes_by_fn["listUsers"]
    assert list_users.method == "QUERY"
    assert list_users.path == "/listUsers"
    assert list_users.request_model is None
    assert list_users.response_model == "User"

    create_order = routes_by_fn["createOrder"]
    assert create_order.method == "MUTATION"
    assert create_order.path == "/createOrder"
    assert create_order.request_model == "OrderInput"
    assert create_order.response_model == "Order"
    assert create_order.line == 19


def test_check_spec_drift_detects_drifted_field_in_prisma_and_graphql(
    tmp_path: Path,
) -> None:
    (tmp_path / "schema.prisma").write_text(
        dedent(
            """\
            model Account {
              id    Int    @id
              email String
            }
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "api.graphql").write_text(
        dedent(
            """\
            type Profile {
              handle: String!
            }
            """
        ),
        encoding="utf-8",
    )

    prd_md = dedent(
        """\
        # Account & Profile PRD

        - `Account.email: String`
        - `Account.plan_tier: String`
        - `Profile.handle: String!`
        """
    )

    repo_map = index_repository(tmp_path)
    report = check_spec_drift(prd_md, repo_map, repo_root=tmp_path)

    assert report.status == "DONE_WITH_CONCERNS"
    assert report.total_spec_contracts == 3
    assert report.matched_contracts == 2
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.category == "missing_field"
    assert "Account.plan_tier" in finding.spec_reference
    assert finding.code_citation == "schema.prisma:1"
