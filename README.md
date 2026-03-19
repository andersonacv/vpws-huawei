# Automação VPWS — Huawei VRP

Script Python para automatizar a criação de circuitos VPWS (Virtual Private Wire Service) em equipamentos Huawei com sistema operacional VRP, via SSH.

## Funcionalidades

- Suporte a múltiplos equipamentos PE em uma única execução
- Verificação de disponibilidade da VLAN antes de criar
- Listagem das interfaces disponíveis com status
- Detecção automática do tipo de interface (**trunk**, **hybrid** ou **access**)
- Liberação correta da VLAN de acordo com o tipo de interface
- Criação de **VLAN**, **VLANIF** e **Pseudowire L2VPN Martini**
- Verificação da configuração aplicada ao final
- Opção de salvar configuração (`save`) no equipamento

## Pré-requisitos

- Python 3.8+
- [uv](https://docs.astral.sh/uv/) instalado
- SSH habilitado nos equipamentos Huawei (`stelnet server enable`)
- MPLS L2VPN habilitado globalmente nos PEs (`mpls l2vpn`)

## Instalação

```bash
# Instalar uv (caso ainda não tenha)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Criar ambiente virtual e instalar dependências
uv sync
```

## Uso

```bash
# Executar diretamente (uv gerencia o ambiente automaticamente)
uv run vpws_huawei.py

# Ou ativar o ambiente e rodar normalmente
.venv\Scripts\activate
python vpws_huawei.py
```

O script solicitará interativamente:

| Parâmetro | Descrição |
|-----------|-----------|
| IP(s) dos PEs | Endereços dos roteadores de borda |
| Usuário / Senha SSH | Credenciais de acesso |
| VLAN ID | ID do circuito (1–4094) |
| Descrição da VLAN | Opcional |
| IP do PE remoto (peer) | Endereço do outro extremo do PW |
| VC-ID | Identificador do Pseudowire |
| IP da Vlanif | Opcional — endereço IP da interface L3 |
| Interface AC | Seleção da interface de cliente |

## Configuração gerada (exemplo)

```
# VLAN
vlan 100
 description VPWS-CLIENTE-X

# VLANIF (opcional)
interface Vlanif100
 ip address 10.0.0.1 255.255.255.252

# Interface AC — liberação da VLAN (trunk)
interface GigabitEthernet0/0/1
 port trunk allow-pass vlan 100

# Subinterface AC + Pseudowire Martini
interface GigabitEthernet0/0/1.100
 vlan-type dot1q 100
 mpls l2vc 10.1.1.2 1001
```

## Arquitetura VPWS

```
    CE-A                PE-A                   PE-B               CE-B
  ┌──────┐   AC      ┌──────┐    PW (MPLS)   ┌──────┐   AC   ┌──────┐
  │      ├──dot1q────┤ VRP  ├───────────────►│ VRP  ├────────┤      │
  └──────┘  VLAN 100 └──────┘  mpls l2vc     └──────┘        └──────┘
```

## Notas importantes

- O MPLS L2VPN precisa estar previamente habilitado: `mpls l2vpn`
- Para interfaces **hybrid**, o script pergunta se a VLAN deve ser tagged ou untagged
- O VC-ID deve ser o **mesmo** nos dois PEs do circuito
- Interfaces de gerência (MEth) e subinterfaces são excluídas da listagem automaticamente
