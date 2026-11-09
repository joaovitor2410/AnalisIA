# Dados sintéticos do portfólio

Criados para este projeto: 120 pedidos, 13 clientes fictícios e seis meses (abril a setembro
de 2026). Os nomes e valores não representam registros de pessoas ou empresas reais.
Estes arquivos são disponibilizados sob a licença MIT do projeto e podem ser usados na demo.

O valor de cada pedido é determinístico: `49,90 + (n × 37 mod 800) + (n mod 4) × 0,25`,
para `n` de 1 a 120. Cada grupo de vinte pedidos corresponde a um mês; o dia vai de 1 a 20.
Os clientes são distribuídos ciclicamente entre os doze primeiros IDs; o 13º não tem pedidos.
Cada nono pedido é cancelado. As quatro regiões também se repetem ciclicamente no cadastro.

`import-options.json` preserva códigos como texto e valores como `DECIMAL(18,2)`.
Não há dependência do conjunto de futebol para executar esta demonstração.
