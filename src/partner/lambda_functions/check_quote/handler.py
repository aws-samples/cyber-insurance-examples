import json
import os
import boto3

cloudfront_url = os.environ.get("CLOUDFRONT_URL")
dynamodb_table_name = os.environ.get("DYNAMODB_TABLE_NAME")
securityhub_findings_bucket = os.environ.get("SECURITYHUB_FINDINGS_BUCKET")

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(dynamodb_table_name)


def lambda_handler(event, context):
    print(f"Received event: {json.dumps(event)}")
    try:
        data = json.loads(event["body"])
        user_account_id = data["accountId"]
        if not user_account_id:
            raise Exception("Error: Missing required parameters: accountId")
        print(f"Checking the quote for user account id: {user_account_id}")
        quote = get_quote(user_account_id)
        if quote:
            formatted_quote = "${:,.3f}".format(quote)
            print(f"Quote found: {formatted_quote}")
            findings = get_findings(user_account_id)
            aggregated_findings = findings_aggregation(findings)
            return {
                "statusCode": 200,
                "body": json.dumps({"status": "success", "quote": formatted_quote, "findings": aggregated_findings}),
                "headers": {
                    "Access-Control-Allow-Origin": f"https://{cloudfront_url}",
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token,X-Amz-User-Agent",
                },
            }
        else:
            print("Quote not found")
            return {
                "statusCode": 404,
                "body": json.dumps({"status": "error", "message": "Quote not found"}),
                "headers": {
                    "Access-Control-Allow-Origin": f"https://{cloudfront_url}",
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token,X-Amz-User-Agent",
                },
            }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": str(e),
            "headers": {
                "Access-Control-Allow-Origin": f"https://{cloudfront_url}",
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token,X-Amz-User-Agent",
            },
        }


def get_quote(user_account_id):
    response = table.get_item(Key={"accountId": user_account_id, "type": "quote"})
    if "Item" in response:
        return response["Item"]["quote"]
    else:
        return None


def get_findings(user_account_id):
    try:
        obj = s3.get_object(
            Bucket=securityhub_findings_bucket,
            Key=f"{user_account_id}/{user_account_id}-findings.json",
        )
        return json.loads(obj["Body"].read())
    except Exception as e:
        print(e)
        return None


def findings_aggregation(findings):
    critical_findings = [finding for finding in findings if finding["Severity"]["Label"] == "CRITICAL"]
    high_findings = [finding for finding in findings if finding["Severity"]["Label"] == "HIGH"]
    medium_findings = [finding for finding in findings if finding["Severity"]["Label"] == "MEDIUM"]
    low_findings = [finding for finding in findings if finding["Severity"]["Label"] == "LOW"]
    informational_findings = [finding for finding in findings if finding["Severity"]["Label"] == "INFORMATIONAL"]
    return {
        "critical": len(critical_findings),
        "high": len(high_findings),
        "medium": len(medium_findings),
        "low": len(low_findings),
        "informational": len(informational_findings),
    }
