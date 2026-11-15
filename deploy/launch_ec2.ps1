# Crée l'instance EC2 qui héberge Peace. À lancer dans le PowerShell où les variables AWS_* sont définies,
# depuis le dossier Datathon2026 :  .\deploy\launch_ec2.ps1
$ErrorActionPreference = "Stop"
$region = "us-east-1"
$ami = aws ssm get-parameter --region $region --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id --query Parameter.Value --output text
$vpc = aws ec2 describe-vpcs --region $region --filters Name=isDefault,Values=true --query "Vpcs[0].VpcId" --output text
$profile = aws iam list-instance-profiles --query "InstanceProfiles[?contains(InstanceProfileName,'ParticipantInstanceProfile')].InstanceProfileName | [0]" --output text
Write-Host "Image $ami, VPC $vpc, profil IAM $profile"
$sg = aws ec2 create-security-group --region $region --group-name peace-web --description "Peace web" --vpc-id $vpc --query GroupId --output text
aws ec2 authorize-security-group-ingress --region $region --group-id $sg --protocol tcp --port 80 --cidr 0.0.0.0/0 | Out-Null
$id = aws ec2 run-instances --region $region --image-id $ami --instance-type t3.small --iam-instance-profile Name=$profile --security-group-ids $sg --user-data file://deploy/user-data.sh --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=peace}]" --query "Instances[0].InstanceId" --output text
Write-Host "Instance $id créée, attente du démarrage..."
aws ec2 wait instance-running --region $region --instance-ids $id
$ip = aws ec2 describe-instances --region $region --instance-ids $id --query "Reservations[0].Instances[0].PublicIpAddress" --output text
Write-Host "Peace sera disponible dans 3 à 5 minutes sur : http://$ip/"
