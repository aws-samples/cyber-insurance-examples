import boto3
import json
import os


dynamodb_table_name = os.environ.get("DYNAMODB_TABLE_NAME")
sns_topic_arn = os.environ.get("SNS_TOPIC_ARN")
user_template_bucket_name = os.environ.get("USER_TEMPLATE_BUCKET_NAME")
partner_iam_role_name = os.environ.get("PARTNER_ROLE_NAME")
partner_account_id = os.environ.get("PARTNER_ACCOUNT_ID")
cloudfront_url = os.environ.get("CLOUDFRONT_URL")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(dynamodb_table_name)
iam = boto3.client("iam")
s3 = boto3.client("s3")
sns = boto3.client("sns")


def lambda_handler(event, context):
    print(f"Received event: {json.dumps(event)}")

    try:
        data = json.loads(event["body"])
        user_account_id = data["accountId"]
        external_id = data["externalId"]
        if not user_account_id or not external_id:
            raise Exception("Error: Missing required parameters: accountId or externalId")
        table.put_item(Item={"accountId": user_account_id, "type": "externalId", "externalId": external_id})

        # Update the S3 bucket policy to allow principals from the user AWS account to access customer-template.yaml
        update_s3_bucket_policy(user_account_id)
        # Update the CreateQuoteLambdaExecutionRole to allow sts:AssumeRole on role in the customer account
        update_lambda_role(user_account_id)
        # Update the SNS topic policy to allow principals from the user AWS account to publish to the topic
        update_sns_topic_policy(user_account_id)

        return {
            "statusCode": 200,
            "body": json.dumps("Account details stored in DynamoDB"),
            "headers": {
                "Access-Control-Allow-Origin": f"https://{cloudfront_url}",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token,X-Amz-User-Agent",
            },
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": str(e),
            "headers": {
                "Access-Control-Allow-Origin": f"https://{cloudfront_url}",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token,X-Amz-User-Agent",
            },
        }


def update_lambda_role(user_account_id):
    try:
        customer_role_arn = "arn:aws:iam::" + user_account_id + ":role/CyberInsuranceQuoteRole-" + partner_account_id
        print(
            f"Updating IAM role policy for role {partner_iam_role_name} to allow sts:AssumeRole on role {customer_role_arn}"
        )
        iam.put_role_policy(
            RoleName=partner_iam_role_name,
            PolicyName="AssumeRolePolicy-" + user_account_id,
            PolicyDocument=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [{"Effect": "Allow", "Action": "sts:AssumeRole", "Resource": customer_role_arn}],
                }
            ),
        )
    except Exception as e:
        print(f"Error: {str(e)}")


def update_s3_bucket_policy(user_account_id):
    print(f"Updating S3 bucket policy for bucket {user_template_bucket_name} to allow access for {user_account_id}")
    new_statement = {
        "Sid": "AllowAccessToCustomerTemplate-" + user_account_id,
        "Effect": "Allow",
        "Principal": {"AWS": "arn:aws:iam::" + user_account_id + ":root"},
        "Action": "s3:GetObject",
        "Resource": "arn:aws:s3:::" + user_template_bucket_name + "/customer-template.yaml",
    }
    try:
        response = s3.get_bucket_policy(Bucket=user_template_bucket_name)
        bucket_policy = json.loads(response["Policy"])
        print(f"Current bucket policy: {json.dumps(bucket_policy)}")
        if not any(statement["Principal"] == new_statement["Principal"] for statement in bucket_policy["Statement"]):
            print(f"Pricipal {new_statement['Principal']} not found in bucket policy. Adding it.")
            bucket_policy["Statement"].append(new_statement)
            print(f"New bucket policy: {json.dumps(bucket_policy)}")
            s3.put_bucket_policy(Bucket=user_template_bucket_name, Policy=json.dumps(bucket_policy))
    except Exception as e:
        print(f"Error: {str(e)}")


def update_sns_topic_policy(user_account_id):
    print(f"Updating SNS topic policy for topic {sns_topic_arn} to allow access for {user_account_id}")
    new_statement = {
        "Sid": "AllowAccessToCustomerTemplate-" + user_account_id,
        "Effect": "Allow",
        "Principal": {"AWS": "arn:aws:iam::" + user_account_id + ":root"},
        "Action": "sns:Publish",
        "Resource": sns_topic_arn,
    }
    try:
        response = sns.get_topic_attributes(TopicArn=sns_topic_arn)
        topic_policy = json.loads(response["Attributes"]["Policy"])
        print(f"Current topic policy: {json.dumps(topic_policy)}")
        if not any(statement["Principal"] == new_statement["Principal"] for statement in topic_policy["Statement"]):
            print(f"Pricipal {new_statement['Principal']} not found in topic policy. Adding it.")
            topic_policy["Statement"].append(new_statement)
            print(f"New topic policy: {json.dumps(topic_policy)}")
            sns.set_topic_attributes(
                TopicArn=sns_topic_arn, AttributeName="Policy", AttributeValue=json.dumps(topic_policy)
            )
    except Exception as e:
        print(f"Error: {str(e)}")
