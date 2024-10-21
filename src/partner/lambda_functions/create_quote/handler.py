import os
import boto3
import json
import logging
from crhelper import CfnResource

logger = logging.getLogger(__name__)
helper = CfnResource(json_logging=False, log_level="DEBUG", boto_level="CRITICAL", sleep_on_delete=120)

dynamodb_table_name = os.environ.get("DYNAMODB_TABLE_NAME")
securityhub_findings_bucket = os.environ["SECURITYHUB_FINDINGS_BUCKET"]

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(dynamodb_table_name)
s3 = boto3.resource("s3")
sts_client = boto3.client("sts")


@helper.create
@helper.update
def get_quote(sns_message, context):
    logger.info("Got Create or Update")
    try:
        customer_role_arn = sns_message["ResourceProperties"]["RoleArn"]
        user_account_id = sns_message["ResourceProperties"]["AccountId"]
        external_id = get_external_id(user_account_id)
        region = get_region(user_account_id)
        if not customer_role_arn or not user_account_id or not external_id or not region:
            raise Exception("Error: Missing required parameters: RoleArn, AccountId, ExternalId, or Region")

        # Store the role ARN in DynamoDB
        store_role_arn(user_account_id, customer_role_arn)
        # Assume the role and get the temporary credentials
        credentials = assume_customer_role(customer_role_arn, external_id)
        # Get the list of findings
        findings = get_securityhub_findings(credentials, region)
        # Analyze the findings and calculate the quote
        store_findings(findings, user_account_id)
        quote = process_findings(findings)
        # Store the quote in DynamoDB
        store_quote(quote, user_account_id)

        helper.Reason = "Successfully processed findings"
        return "MyResourceId"
    except Exception as e:
        logger.error(f"Error processing findings: {e}")
        raise


@helper.delete
def delete(sns_message, context):
    logger.info("Got Delete")
    user_account_id = sns_message["ResourceProperties"]["AccountId"]
    logger.info(
        f"Customer {user_account_id} deleted the cross-account role. You no longer have access to Security Hub findings in their account."
    )


def lambda_handler(event, context):
    sns_message = json.loads(event["Records"][0]["Sns"]["Message"])
    helper(sns_message, context)


def get_external_id(user_account_id):
    response = table.get_item(Key={"accountId": user_account_id, "type": "externalId"})
    external_id = response["Item"]["externalId"]
    return external_id


def get_region(user_account_id):
    response = table.get_item(Key={"accountId": user_account_id, "type": "region"})
    region = response["Item"]["region"]
    return region


def get_securityhub_findings(credentials, region):
    logger.info("Getting Security Hub findings...")
    securityhub = boto3.client(
        "securityhub",
        region_name=region,
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
    )

    filters = {
        "ComplianceAssociatedStandardsId": [
            {
                "Comparison": "EQUALS",
                "Value": "standards/aws-foundational-security-best-practices/v/1.0.0",
            }
        ]
    }
    response = securityhub.get_findings(Filters=filters)
    findings = response["Findings"]
    while "NextToken" in response:
        response = securityhub.get_findings(
            Filters=filters,
            NextToken=response["NextToken"],
        )
        findings.extend(response["Findings"])
    return findings


def store_role_arn(user_account_id, role_arn):
    logger.info("Storing role ARN in DynamoDB table...")
    table.put_item(Item={"accountId": user_account_id, "type": "roleArn", "roleArn": role_arn})
    logger.info("Role ARN stored in DynamoDB table")


def assume_customer_role(customer_role_arn, external_id):
    logger.info(f"Assuming role {customer_role_arn} with external ID {external_id}")
    assumed_role_object = sts_client.assume_role(
        RoleArn=customer_role_arn,
        ExternalId=external_id,
        RoleSessionName="AssumeRoleCyberinsuranceProvider",
    )
    try:
        credentials = assumed_role_object["Credentials"]
        logger.info("Temporary credentials obtained")
    except KeyError:
        logger.info("Error: Unable to get temporary credentials")
        raise
    return credentials


def process_findings(findings):
    # Add any custom logic here
    # Example: Print the number of findings
    logger.info(f"Total number of findings: {len(findings)}")
    
    failed_findings = [finding for finding in findings if finding["Compliance"]["Status"] == "FAILED"]
    passed_findings = [finding for finding in findings if finding["Compliance"]["Status"] == "PASSED"]
    warnings_findings = [finding for finding in findings if finding["Compliance"]["Status"] == "WARNING"]
    not_available_findings = [finding for finding in findings if finding["Compliance"]["Status"] == "NOT_AVAILABLE"]
    
    critical_findings = [finding for finding in findings if finding["Severity"]["Label"] == "CRITICAL"]
    high_findings = [finding for finding in findings if finding["Severity"]["Label"] == "HIGH"]
    medium_findings = [finding for finding in findings if finding["Severity"]["Label"] == "MEDIUM"]
    low_findings = [finding for finding in findings if finding["Severity"]["Label"] == "LOW"]
    informational_findings = [finding for finding in findings if finding["Severity"]["Label"] == "INFORMATIONAL"]
    
    logger.info(f"Number of failed findings: {len(failed_findings)}")
    logger.info(f"Number of passed findings: {len(passed_findings)}")
    logger.info(f"Number of warning findings: {len(warnings_findings)}")
    logger.info(f"Number of not available findings: {len(not_available_findings)}")
    logger.info(f"Number of critical findings: {len(critical_findings)}")
    logger.info(f"Number of high findings: {len(high_findings)}")
    logger.info(f"Number of medium findings: {len(medium_findings)}")
    logger.info(f"Number of low findings: {len(low_findings)}")
    logger.info(f"Number of informational findings: {len(informational_findings)}")
    
    # Quote calculation logic example
    # 1 critical finding = $1000
    # 1 high finding = $500
    # 1 medium finding = $100
    # 1 low finding = $10
    # 1 informational finding = $1
    quote = (
        len(critical_findings) * 1000
        + len(high_findings) * 500
        + len(medium_findings) * 100
        + len(low_findings) * 10
        + len(informational_findings) * 1
    )
    logger.info(f"Quote: ${quote}")
    return quote


def store_findings(findings, user_account_id):
    logger.info("Storing findings in S3 bucket...")
    findings_file_name = f"{user_account_id}-findings.json"
    s3object = s3.Object(securityhub_findings_bucket, user_account_id + "/" + findings_file_name)
    s3object.put(Body=(json.dumps(findings)))
    logger.info("Findings stored in S3 bucket")


def store_quote(quote, user_account_id):
    logger.info("Storing quote in DynamoDB table...")
    table.put_item(Item={"accountId": user_account_id, "type": "quote", "quote": quote})
    logger.info("Quote stored in DynamoDB table")
