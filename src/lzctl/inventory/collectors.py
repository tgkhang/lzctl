"""Built-in collectors. Each yields dicts with the base keys (id, name, state,
created, tags) plus its own ``columns``. Account/region/service are added by the
caller.

Adding one is a single decorated function; keep calls paginated and read-only.
"""

from __future__ import annotations

import botocore.exceptions

from . import collector, tags_of


def _fmt(dt) -> str | None:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else None


@collector("ec2", "EC2 instances",
           ("type", "private_ip", "public_ip", "vpc_id", "platform"))
def ec2_instances(session, region):
    client = session.client("ec2", region_name=region)
    for page in client.get_paginator("describe_instances").paginate():
        for reservation in page["Reservations"]:
            for inst in reservation["Instances"]:
                tags = tags_of(inst.get("Tags"))
                yield {
                    "id": inst["InstanceId"],
                    "name": tags.get("Name"),
                    "state": inst["State"]["Name"],
                    "created": _fmt(inst.get("LaunchTime")),
                    "tags": tags,
                    "type": inst.get("InstanceType"),
                    "private_ip": inst.get("PrivateIpAddress"),
                    "public_ip": inst.get("PublicIpAddress"),
                    "vpc_id": inst.get("VpcId"),
                    "platform": inst.get("PlatformDetails"),
                }


@collector("ebs", "EBS volumes", ("size_gb", "volume_type", "encrypted", "attached_to"))
def ebs_volumes(session, region):
    client = session.client("ec2", region_name=region)
    for page in client.get_paginator("describe_volumes").paginate():
        for vol in page["Volumes"]:
            tags = tags_of(vol.get("Tags"))
            yield {
                "id": vol["VolumeId"],
                "name": tags.get("Name"),
                "state": vol["State"],
                "created": _fmt(vol.get("CreateTime")),
                "tags": tags,
                "size_gb": vol.get("Size"),
                "volume_type": vol.get("VolumeType"),
                "encrypted": vol.get("Encrypted"),
                "attached_to": ",".join(a["InstanceId"] for a in vol.get("Attachments", [])) or None,
            }


@collector("rds", "RDS database instances",
           ("engine", "engine_version", "instance_class", "multi_az", "storage_gb"))
def rds_instances(session, region):
    client = session.client("rds", region_name=region)
    for page in client.get_paginator("describe_db_instances").paginate():
        for db in page["DBInstances"]:
            yield {
                "id": db["DBInstanceIdentifier"],
                "name": db.get("DBName"),
                "state": db.get("DBInstanceStatus"),
                "created": _fmt(db.get("InstanceCreateTime")),
                "tags": tags_of(db.get("TagList")),
                "engine": db.get("Engine"),
                "engine_version": db.get("EngineVersion"),
                "instance_class": db.get("DBInstanceClass"),
                "multi_az": db.get("MultiAZ"),
                "storage_gb": db.get("AllocatedStorage"),
            }


@collector("s3", "S3 buckets", ("bucket_region",), global_service=True)
def s3_buckets(session, region):
    client = session.client("s3", region_name=region)
    for bucket in client.list_buckets().get("Buckets", []):
        name = bucket["Name"]
        try:
            location = client.get_bucket_location(Bucket=name).get("LocationConstraint")
        except botocore.exceptions.ClientError:
            location = None
        try:
            tags = tags_of(client.get_bucket_tagging(Bucket=name).get("TagSet"))
        except botocore.exceptions.ClientError:
            tags = {}  # NoSuchTagSet, or no permission
        yield {
            "id": name,
            "name": name,
            "state": None,
            "created": _fmt(bucket.get("CreationDate")),
            "tags": tags,
            "bucket_region": location or "us-east-1",
        }


@collector("lambda", "Lambda functions", ("runtime", "memory_mb", "last_modified"))
def lambda_functions(session, region):
    client = session.client("lambda", region_name=region)
    for page in client.get_paginator("list_functions").paginate():
        for fn in page["Functions"]:
            try:
                tags = client.list_tags(Resource=fn["FunctionArn"]).get("Tags", {})
            except botocore.exceptions.ClientError:
                tags = {}
            yield {
                "id": fn["FunctionName"],
                "name": fn["FunctionName"],
                "state": fn.get("State"),
                "created": None,
                "tags": tags,
                "runtime": fn.get("Runtime"),
                "memory_mb": fn.get("MemorySize"),
                "last_modified": (fn.get("LastModified") or "")[:16].replace("T", " ") or None,
            }


@collector("dynamodb", "DynamoDB tables", ("item_count", "size_bytes", "billing_mode"))
def dynamodb_tables(session, region):
    client = session.client("dynamodb", region_name=region)
    for page in client.get_paginator("list_tables").paginate():
        for name in page["TableNames"]:
            table = client.describe_table(TableName=name)["Table"]
            try:
                tags = tags_of(client.list_tags_of_resource(ResourceArn=table["TableArn"]).get("Tags"))
            except botocore.exceptions.ClientError:
                tags = {}
            yield {
                "id": name,
                "name": name,
                "state": table.get("TableStatus"),
                "created": _fmt(table.get("CreationDateTime")),
                "tags": tags,
                "item_count": table.get("ItemCount"),
                "size_bytes": table.get("TableSizeBytes"),
                "billing_mode": (table.get("BillingModeSummary") or {}).get("BillingMode", "PROVISIONED"),
            }


@collector("elb", "Application/Network load balancers", ("type", "scheme", "dns_name"))
def load_balancers(session, region):
    client = session.client("elbv2", region_name=region)
    lbs = [lb for page in client.get_paginator("describe_load_balancers").paginate()
           for lb in page["LoadBalancers"]]
    tags: dict[str, dict[str, str]] = {}
    for i in range(0, len(lbs), 20):  # describe_tags accepts 20 ARNs per call
        arns = [lb["LoadBalancerArn"] for lb in lbs[i:i + 20]]
        for desc in client.describe_tags(ResourceArns=arns)["TagDescriptions"]:
            tags[desc["ResourceArn"]] = tags_of(desc.get("Tags"))
    for lb in lbs:
        yield {
            "id": lb["LoadBalancerName"],
            "name": lb["LoadBalancerName"],
            "state": (lb.get("State") or {}).get("Code"),
            "created": _fmt(lb.get("CreatedTime")),
            "tags": tags.get(lb["LoadBalancerArn"], {}),
            "type": lb.get("Type"),
            "scheme": lb.get("Scheme"),
            "dns_name": lb.get("DNSName"),
        }
