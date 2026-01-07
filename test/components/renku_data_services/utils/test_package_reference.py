from renku_data_services.base_models.nel import Nel
from renku_data_services.utils.package_reference import (
    Digest,
    Domain,
    DomainName,
    Ipv4Address,
    PackageReference,
)


def test_parse_digest():
    d1 = Digest.parse("sha256:7cc4b5aefd1d0cadf8d97d4350462ba51")
    assert d1.algorithm == Nel.of("sha256")
    assert d1.digest_hex == "7cc4b5aefd1d0cadf8d97d4350462ba51"

    d2 = Digest.parse("sha256+sha512:7cc4b5aefd1d0cadf8d97d4350462ba51")
    assert d2.algorithm == Nel.of("sha256", "sha512")
    assert d2.digest_hex == "7cc4b5aefd1d0cadf8d97d4350462ba51"


def test_parse_domain():
    domain = Domain.parse("123456789012.dkr.ecr.us-west-2.amazonaws.com")
    assert domain.port is None
    assert domain.host == DomainName(Nel.unsafe_from_list("123456789012.dkr.ecr.us-west-2.amazonaws.com".split(".")))


def test_parse_ipv4():
    result = Domain.parse("192.168.1.122")
    assert result.host == Ipv4Address(192, 168, 1, 122)


def test_parse_reference1():
    ref = "docker.io/library/busybox:latest@sha256:7cc4b5aefd1d0cadf8d97d4350462ba51c694ebca145b08d7d41b41acc8db5aa"
    result = PackageReference.parse(ref)
    assert result.name.domain is not None
    assert result.name.domain.host == DomainName(Nel.of("docker", "io"))
    assert result.name.domain.port is None
    assert result.name.path == Nel.of("library", "busybox")
    assert result.tag == "latest"
    assert result.digest is not None
    assert result.digest.algorithm == Nel.of("sha256")
    assert result.digest.digest_hex == "7cc4b5aefd1d0cadf8d97d4350462ba51c694ebca145b08d7d41b41acc8db5aa"
    assert str(result) == ref


def test_parse_reference2():
    ref = "docs/dhi-python@sha256:94a00394bc5a8ef503fb59db0a7d0ae9e1110866e8aee8ba40cd864cea69ea1a"
    result = PackageReference.parse(ref)
    assert result.name.domain is not None
    assert result.name.domain.host == DomainName(Nel.of("docs"))
    assert result.name.domain.port is None
    assert result.name.path == Nel.of("dhi-python")
    assert result.tag is None
    assert result.digest is not None
    assert result.digest.algorithm == Nel.of("sha256")
    assert result.digest.digest_hex == "94a00394bc5a8ef503fb59db0a7d0ae9e1110866e8aee8ba40cd864cea69ea1a"
    assert str(result) == ref


def test_parse_reference3():
    result = PackageReference.parse("nginx:latest")
    assert result.name.domain is None
    assert result.name.path == Nel.of("nginx")
    assert result.digest is None
    assert result.tag == "latest"
    assert str(result) == "nginx:latest"


def test_parse_reference4():
    ref = "gcr.io/my-project/myimage:v1.0"
    result = PackageReference.parse(ref)
    assert result.digest is None
    assert result.tag == "v1.0"
    assert result.name.domain is not None
    assert result.name.domain.host == DomainName(Nel.of("gcr", "io"))
    assert result.name.domain.port is None
    assert result.name.path == Nel.of("my-project", "myimage")
    assert str(result) == ref


def test_parse_reference5():
    ref = "123456789012.dkr.ecr.us-west-2.amazonaws.com/my-app:latest"
    result = PackageReference.parse(ref)
    assert result.digest is None
    assert result.tag == "latest"
    assert result.name.domain is not None
    assert result.name.domain.host == DomainName(Nel.of("123456789012", "dkr", "ecr", "us-west-2", "amazonaws", "com"))
    assert result.name.domain.port is None
    assert result.name.path == Nel.of("my-app")
    assert str(result) == ref


def test_parse_reference6():
    ref = "myregistry.azurecr.io/myapp:dev"
    result = PackageReference.parse(ref)
    assert result.digest is None
    assert result.tag == "dev"
    assert result.name.domain is not None
    assert result.name.domain.host == DomainName(Nel.of("myregistry", "azurecr", "io"))
    assert result.name.domain.port is None
    assert result.name.path == Nel.of("myapp")
    assert str(result) == ref
