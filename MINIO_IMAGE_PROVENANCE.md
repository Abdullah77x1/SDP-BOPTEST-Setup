**Note for this GitHub package:** The localhost Compose override distributed here is `compose.team.yml`. The historical `deployment/compose.localhost.override.yml` path below refers to the original SDP pilot, not a file included in this repository. The referenced independent archive evidence is also not shipped here.

# Verified recovery of the pinned MinIO images

14 November 2026. **Both requested Linux/AMD64 image-manifest digests and their historical original-image provenance are VERIFIED. Both images were pulled by digest and retagged locally.**

| Original BOPTEST dependency | Authorized archive | Verified platform-manifest SHA-256 |
|---|---|---|
| minio/minio:RELEASE.2025-04-22T22-12-26Z | mttjsc/minio | `3f97c5651cb6662b880c787a232b6b34fec8d8922e08d6617b25d241a21164bb` |
| minio/mc:RELEASE.2025-04-16T18-13-26Z | clickhouse/minio-mc | `2582c2f48b1e31545143ba5285c67d7b38c8b8f6912142d0630686dc7aaac28b` |

## Independent historical verification

The current archive registries were not used as their own sole provenance evidence. Wayback captures of the **original `minio/minio` and `minio/mc` Docker Hub pages** were retrieved and preserved. Although these captured pages select another architecture in their URL, their embedded whole-tag metadata contains all architecture records. That metadata was decoded, and the release name, Linux OS, AMD64 architecture and full 64-character child-manifest digest were explicitly checked.

- Server: [original Docker Hub page captured 1 September 2026](https://web.archive.org/web/20260901034234id_/https://hub.docker.com/layers/minio/minio/RELEASE.2025-04-22T22-12-26Z/images/sha256-106abffd1b575a2465443f8907c041e019fbed6475425bc40fffdf19a106962d?tab=layers).
- Client: [original Docker Hub page captured 4 August 2026](https://web.archive.org/web/20260804025219id_/https://hub.docker.com/layers/minio/mc/RELEASE.2025-04-16T18-13-26Z/images/sha256-595f183c0cc2b92626e038e5b30e5a9a5a02d350446bf1374266059f3c122a5a).

Each historical AMD64 digest equals both the user-supplied expectation and the hash independently computed from the current archive's raw AMD64 manifest bytes. The historical multi-platform index hashes also match the archive tag manifests: server `a1ea29fa28355559ef137d71fc570e508a214ec84ff8083e39bc5428980b015e`; client `aead63c77f9db9107f1696fb08ecb0faeda23729cde94b0f663edf4fe09728e3`.

The AMD64 manifests reference config blobs. Their bytes were independently hashed against those references, and the configs identify Linux/AMD64. Docker subsequently fetched the actual layer content by the pinned platform digests. This verifies content identity to the historical records; it is not a signed publisher attestation or a new security/physical-model validation.

Raw manifests, config blobs, original archived HTML, CDX metadata, decoded historical tag metadata, gate record, pull logs and local image inspection are in `evidence/minio_archive_verification`. An early server capture lacking the digest was not used to establish the gate; the later complete capture above was used. Public-registry bearer tokens were not written into evidence.

## Actual retrieval and local retagging

```powershell
docker pull --platform linux/amd64 'mttjsc/minio@sha256:3f97c5651cb6662b880c787a232b6b34fec8d8922e08d6617b25d241a21164bb'
docker pull --platform linux/amd64 'clickhouse/minio-mc@sha256:2582c2f48b1e31545143ba5285c67d7b38c8b8f6912142d0630686dc7aaac28b'
docker tag 'mttjsc/minio@sha256:3f97c5651cb6662b880c787a232b6b34fec8d8922e08d6617b25d241a21164bb' 'minio/minio:RELEASE.2025-04-22T22-12-26Z'
docker tag 'clickhouse/minio-mc@sha256:2582c2f48b1e31545143ba5285c67d7b38c8b8f6912142d0630686dc7aaac28b' 'minio/mc:RELEASE.2025-04-16T18-13-26Z'
```

Both pull logs report the exact expected digest and success. Local inspection records the original-name tags and archive RepoDigests. Multi-platform index hashes, platform-manifest hashes, config hashes and Docker image IDs are retained separately; they are not assumed interchangeable.

The official BOPTEST release remains unchanged. A separate `deployment/compose.localhost.override.yml` changes only publishing addresses, using `!override` to replace rather than append ports. Resolved configuration verifies 127.0.0.1 for API 80 and MinIO 9000/9001. Image recovery does not by itself prove BOPTEST startup, runtime compatibility, A/B execution or live dashboard success; those are reported separately.
