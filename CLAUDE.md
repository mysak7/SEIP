Ahoj, potřebuji zrefaktorovat můj stávající Terraform projekt, který běží na AWS. 
Cílem je zachovat můj současný "Deep Mind" projekt běžící na EC2/ASG tak, jak je (má svůj vlastní život a Terraform ho dál spravuje). K tomu chci do stejného VPC a podsítí PŘIDAT Amazon EKS s nainstalovaným Karpenterem pro můj nový Orchestrátor. 

Protože už nechci používat ASG s CloudWatch alarmy pro škálování nových aplikací, chci do EKS nainstalovat KEDA (Kubernetes Event-driven Autoscaler).

Zároveň potřebuji vyřešit bezpečné mazání prostředí (EKS + Karpenter), aby nevznikaly "osiřelé" (orphaned) EC2 instance, o kterých Terraform neví. Chci, aby se všechny uzly daly odstranit (tzv. "vypínací/hladovějící skript") v Bashi, před tím, než se spustí `terraform destroy`.

Zde je seznam úkolů, které potřebuji, abys udělal:

1. Modulární Terraform struktura:
Vytvoř nový adresář `modules/eks/`. Napiš mi obsah těchto souborů:
- `modules/eks/main.tf` (Základní EKS Control Plane běžící ve stejném VPC jako zbytek systému).
- `modules/eks/karpenter.tf` (Instalace Karpenteru přes Helm, vč. IAM rolí a OIDC).
- `modules/eks/keda.tf` (Instalace KEDA přes Helm, s IAM IRSA oprávněním pro přístup ke CloudWatch a DynamoDB).
- `modules/eks/variables.tf` a `outputs.tf`.

2. Integrace do `seip-infrastructure.tf`:
Ukaž mi, jak tento nový `eks` modul zavolám z mého kořenového `seip-infrastructure.tf` a jak mu předám VPC ID a privátní podsítě z mého `module.vpc`. Můj stávající `aws_autoscaling_group` pro Deep Mind musí v kódu zůstat netknutý.

3. Konfigurace Karpenteru (NodePools):
Napiš mi vzorový YAML pro Karpenter `NodePool` a `EC2NodeClass`. Zajisti, aby:
- Se instaloval do mých privátních subnetů.
- Měl nastavený label/tag (např. `karpenter.sh/discovery`), aby se EC2 instance vytvořené Karpenterem oddělily od mé ASG instance `dev-deep-mind-worker`.
- Měl nastaveno `consolidationPolicy: WhenEmpty` nebo `WhenUnderutilized`, aby mohl cluster škálovat k nule.

4. Konfigurace KEDA (ScaledObject):
Napiš mi vzorový YAML manifest pro KEDA `ScaledObject` a `TriggerAuthentication`. Tento objekt se bude dívat do CloudWatch na metriku `UnprocessedEvents` (ve jmenném prostoru `SEIPDeepMind`) nebo přímo dotazovat DynamoDB. Pokud metrika stoupne nad 30, musí zvednout počet replik (Podů) z 0 až na max. 5.

5. Vypínací / Cleanup skript (Bash):
Vytvoř mi Bash skript (např. `cleanup_eks.sh`), který zajistí, že při mém pokusu vše zbourat nevzniknou osiřelé uzly. Skript by měl pomocí `kubectl` a `aws cli`:
- Smazat všechny ScaledObjects z KEDA (čímž Pody klesnou na 0).
- Smazat všetky Karpenter NodePools (`kubectl delete nodepool --all`).
- Smazat NodeClaims a uzly patřící Karpenteru (`kubectl delete nodes -l karpenter.sh/nodepool`).
- Až bude vše prázdné, skript by měl spustit `terraform destroy -target=module.eks_cluster` pro smazání EKS, aniž by to smazalo moji základní VPC a ASG síť.

Prosím, všechna řešení piš jako clean code, popiš kroky k nasazení a předpokládej Linux (Bash) prostředí, jelikož pracuji ve WSL.