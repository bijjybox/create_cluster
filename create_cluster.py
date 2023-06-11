import os
import subprocess
from configparser import ConfigParser

# Create a ConfigParser object.
config = ConfigParser()

# Read the config file.
config.read("config.ini")

# Get the AWS account ID and region from the config file.
aws_account_id = config["aws"]["aws_account_id"]
aws_region = config["aws"]["aws_region"]

# Create a VPC and subnets for the cluster.
vpc_id = subprocess.check_output(["aws", "ec2", "create-vpc", "--cidr-block", config["vpc"]["cidr_block"]]).decode("utf-8").strip()
subnet_ids = []
for subnet_cidr_block in config["subnets"]["cidr_blocks"]:
    subnet_id = subprocess.check_output(["aws", "ec2", "create-subnet", "--vpc-id", vpc_id, "--cidr-block", subnet_cidr_block]).decode("utf-8").strip()
    subnet_ids.append(subnet_id)

# Create a Kubernetes control plane.
cluster_name = "my-cluster"
eksctl_command = ["eksctl", "create", "cluster", "--name", cluster_name, "--region", aws_region, "--vpc-id", vpc_id, "--subnets", subnet_ids]
subprocess.call(eksctl_command)

# Create worker nodes for the cluster.
node_count = config["nodes"]["count"]
node_type = config["nodes"]["type"]
eksctl_command = ["eksctl", "create", "nodegroup", "--cluster", cluster_name, "--node-type", node_type, "--nodes", node_count]
subprocess.call(eksctl_command)

# Create a namespace for each environment.
environments = config["environments"]
for environment in environments:
    namespace = environments[environment + "_namespace"]
    kubectl_command = ["kubectl", "create", "namespace", namespace]
    subprocess.call(kubectl_command)

    # Create AWS secrets for the namespace.
    secret_name = f"aws-secret-{environment}"
    aws_access_key_id = config["aws_access_key_id"]  
    aws_secret_access_key = config["aws_secret_access_key"]  
    kubectl_command = [
        "kubectl",
        "create",
        "secret",
        "generic",
        secret_name,
        f"--namespace={namespace}",
        f"--from-literal=AWS_ACCESS_KEY_ID={aws_access_key_id}",
        f"--from-literal=AWS_SECRET_ACCESS_KEY={aws_secret_access_key}",
    ]
    subprocess.call(kubectl_command)

    # Deploy the application to the namespace with the AWS secrets.
    replicas = environments.getint(environment + "_replicas")
    image = environments[environment + "_image"]

    app_yaml = f"""
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: my-app
      namespace: {namespace}
    spec:
      replicas: {replicas}
      selector:
        matchLabels:
          app: my-app
      template:
        metadata:
          labels:
            app: my-app
        spec:
          containers:
            - name: my-app
              image: {image}
              imagePullPolicy: Always
              env:
                - name: AWS_ACCESS_KEY_ID
                  valueFrom:
                    secretKeyRef:
                      name: {secret_name}
                      key: AWS_ACCESS_KEY_ID
                - name: AWS_SECRET_ACCESS_KEY
                  valueFrom:
                    secretKeyRef:
                      name: {secret_name}
                      key: AWS_SECRET_ACCESS_KEY
    """

    kubectl_command = ["kubectl", "apply", "-f", "-", f"--namespace={namespace}"]
    subprocess.call(kubectl_command, input=app_yaml, text=True)

# Create IAM roles and policies for EKS cluster and worker nodes
iam_config = config["iam"]
cluster_role_name = iam_config["cluster_role_name"]
worker_node_role_name = iam_config["worker_node_role_name"]

# Create IAM roles and attach policies for the cluster
create_cluster_role_command = [
    "aws", "iam", "create-role",
    "--role-name", cluster_role_name,
    "--assume-role-policy-document", iam_config["cluster_role_policy"],
]
subprocess.call(create_cluster_role_command)

attach_cluster_role_policy_command = [
    "aws", "iam", "attach-role-policy",
    "--role-name", cluster_role_name,
    "--policy-arn", iam_config["cluster_role_policy_arn"],
]
subprocess.call(attach_cluster_role_policy_command)

# Create IAM roles and attach policies for the worker nodes
create_worker_node_role_command = [
    "aws", "iam", "create-role",
    "--role-name", worker_node_role_name,
    "--assume-role-policy-document", iam_config["worker_node_role_policy"],
]
subprocess.call(create_worker_node_role_command)

attach_worker_node_role_policy_command = [
    "aws", "iam", "attach-role-policy",
    "--role-name", worker_node_role_name,
    "--policy-arn", iam_config["worker_node_role_policy_arn"],
]
subprocess.call(attach_worker_node_role_policy_command)

# Configure Security Groups for EKS cluster
security_group_ids = []
for sg_cidr in config["security_groups"]["allowed_cidrs"]:
    create_security_group_command = [
        "aws", "ec2", "create-security-group",
        "--group-name", config["security_groups"]["group_name"],
        "--description", config["security_groups"]["group_description"],
        "--vpc-id", vpc_id,
    ]
    security_group_id = subprocess.check_output(create_security_group_command).decode("utf-8").strip()
    
    authorize_ingress_command = [
        "aws", "ec2", "authorize-security-group-ingress",
        "--group-id", security_group_id,
        "--protocol", config["security_groups"]["protocol"],
        "--port", config["security_groups"]["port"],
        "--cidr", sg_cidr,
    ]
    subprocess.call(authorize_ingress_command)
    
    security_group_ids.append(security_group_id)


