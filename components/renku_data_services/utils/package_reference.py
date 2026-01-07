"""Implement package references.

Package references provide a general type to represent referencing images within a registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import parsy as p
from parsy import Parser

from renku_data_services.base_models.nel import Nel


@dataclass
class Digest:
    """The encoded digest and algorithm."""

    algorithm: Nel[str]
    digest_hex: str

    def __str__(self) -> str:
        return f"{"_".join(self.algorithm)}:{self.digest_hex}"

    @classmethod
    def parse(cls, s: str) -> Digest:
        """Parse a digest string."""
        return cast(Digest, _PackageReferenceParser.digest.parse(s.strip()))


@dataclass
class DomainName:
    """A domain name constisting of at least one component."""

    components: Nel[str]

    def __str__(self) -> str:
        return ".".join(self.components)


@dataclass
class Ipv4Address:
    """A ipv4 address."""

    octet1: int
    octet2: int
    octet3: int
    octet4: int

    def __str__(self) -> str:
        return f"{self.octet1}.{self.octet2}.{self.octet3}.{self.octet4}"


type Host = Ipv4Address | DomainName


@dataclass
class Domain:
    """A domain with optional port."""

    host: Host
    port: int | None

    def __str__(self) -> str:
        return f"{self.host}:{self.port}" if self.port else str(self.host)

    @classmethod
    def parse(cls, s: str) -> Domain:
        """Parses a domain."""
        return cast(Domain, _PackageReferenceParser.domain.parse(s.strip()))


@dataclass
class PackageName:
    """A package or image name."""

    domain: Domain | None
    path: Nel[str]

    def __str__(self) -> str:
        return f"{self.domain}/{"/".join(self.path)}" if self.domain else "/".join(self.path)

    @classmethod
    def parse(cls, s: str) -> PackageName:
        """Parses a package name."""
        return cast(PackageName, _PackageReferenceParser.name.parse(s.strip()))


@dataclass
class PackageReference:
    """A package reference."""

    name: PackageName
    tag: str | None
    digest: Digest | None

    def __str__(self) -> str:
        tag_suf = f":{self.tag}" if self.tag else ""
        dig_suf = f"@{self.digest}" if self.digest else ""
        return f"{self.name}{tag_suf}{dig_suf}"

    @classmethod
    def parse(cls, s: str) -> PackageReference:
        """Parses a package reference string."""
        return cast(PackageReference, _PackageReferenceParser.reference.parse(s.strip()))


class _ParserHelper:
    @classmethod
    def is_alpha_lc(cls, c: str) -> bool:
        return c >= "a" and c <= "z"

    @classmethod
    def is_alpha(cls, c: str) -> bool:
        return cls.is_alpha_lc(c) or (c >= "A" and c <= "Z")

    @classmethod
    def is_alphanum(cls, c: str) -> bool:
        return cls.is_alpha(c) or (c >= "0" and c <= "9")

    @classmethod
    def is_alphanum_lc(cls, c: str) -> bool:
        return cls.is_alpha_lc(c) or (c >= "0" and c <= "9")

    @classmethod
    def is_ident(cls, c: str) -> bool:
        return (c >= "a" and c <= "f") or (c >= "0" and c <= "9")

    @classmethod
    def is_word(cls, c: str) -> bool:
        return cls.is_alphanum(c) or c == "_"

    @classmethod
    def is_alphanum_hyphen(cls, c: str) -> bool:
        return cls.is_alphanum(c) or c == "-"

    @classmethod
    def is_word_ext(cls, c: str) -> bool:
        return cls.is_word(c) or c in ".-"

    @classmethod
    def is_hex(cls, c: str) -> bool:
        return (c >= "a" and c <= "f") or (c >= "A" and c <= "Z") or (c >= "0" and c <= "9")


class _PackageReferenceParser:
    """Parser for image references, grammar from https://pkg.go.dev/github.com/distribution/reference."""

    alpha: Parser = p.test_char(_ParserHelper.is_alpha, "[a-zA-Z]")
    alphanum: Parser = p.test_char(_ParserHelper.is_alphanum, "[a-zA-Z0-9]")
    alphanum_hyphen: Parser = p.test_char(_ParserHelper.is_alphanum_hyphen, "[a-zA-Z0-9-]")
    hex_str: Parser = p.test_char(_ParserHelper.is_hex, "[a-f0-9]")

    identifier: Parser = (p.test_char(_ParserHelper.is_ident, "identifier(1-64)").at_most(64).at_least(1)).concat()
    digest_hex: Parser = hex_str.at_least(32).concat()
    digest_algo_component: Parser = p.seq(alpha, alphanum.many().concat()).concat()
    digest_algo_sep: Parser = p.char_from("+.-_")
    digest_algo: Parser = digest_algo_component.sep_by(digest_algo_sep, min=1).map(Nel.unsafe_from_list)
    digest: Parser = p.seq(digest_algo, p.string(":") >> digest_hex).map(lambda e: Digest(e[0], e[1]))

    tag: Parser = p.seq(
        p.test_char(_ParserHelper.is_word, "[A-Za-z0-9_]"),
        p.test_char(_ParserHelper.is_word_ext, "[A-Za-z0-9_.-]").at_most(127).concat(),
    ).concat()

    path_comp_sep: Parser = p.alt(
        p.string("__"), p.test_char(lambda c: c in "_.", "[_.]"), p.string("-").at_least(1)
    ).concat()

    path_component: Parser = p.seq(alphanum, p.alt(alphanum, path_comp_sep).many().concat()).concat()
    path: Parser = path_component.sep_by(p.string("/"), min=1).map(Nel.unsafe_from_list)

    port_number: Parser = p.digit.at_least(1).concat()

    domain_component: Parser = (
        alphanum_hyphen.at_least(1)
        .concat()
        .bind(
            lambda result: p.success(result)
            if result != "" and result[-1].isalnum()
            else p.fail("Must end with alphanum")
        )
    )
    domain_name: Parser = domain_component.sep_by(p.string("."), min=1).map(Nel.unsafe_from_list).map(DomainName)

    dec_octet: Parser = (
        p.digit.times(min=1, max=3)
        .concat()
        .map(int)
        .bind(lambda num: p.success(num) if num >= 0 and num <= 255 else p.fail(f"Invalid ipv4 octet: {num}"))
    )

    ipv4: Parser = p.seq(
        dec_octet, p.string(".") >> dec_octet, p.string(".") >> dec_octet, p.string(".") >> dec_octet
    ).map(lambda e: Ipv4Address(e[0], e[1], e[2], e[3]))

    host: Parser = p.alt(ipv4, domain_name)
    domain: Parser = p.seq(host, (p.string(":") >> port_number).optional()).map(lambda e: Domain(e[0], e[1]))

    name: Parser = p.seq((domain << p.string("/")).optional(), path).map(lambda e: PackageName(e[0], e[1]))

    reference: Parser = p.seq(name, (p.string(":") >> tag).optional(), (p.string("@") >> digest).optional()).map(
        lambda e: PackageReference(e[0], e[1], e[2])
    )
