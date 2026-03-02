const { ethers, upgrades } = require("hardhat");

function average(values) {
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function toMs(startNs, endNs) {
  return Number(endNs - startNs) / 1_000_000;
}

function computeStats(values) {
  return {
    avg: average(values),
    min: Math.min(...values),
    max: Math.max(...values),
    runs: values.length,
  };
}

function padCell(value, width, align = "left") {
  const text = String(value);
  if (align === "right") {
    return text.padStart(width, " ");
  }
  return text.padEnd(width, " ");
}

function printLatencyTable(title, rows) {
  const separator = "-".repeat(78);
  const columns = {
    case: 36,
    avg: 11,
    min: 11,
    max: 11,
    runs: 9,
  };

  const allSamples = rows.flatMap((row) => row.samples);
  const overall = computeStats(allSamples);

  console.log("\n" + title);
  console.log(separator);
  console.log(
    `${padCell("Case", columns.case)}${padCell("Avg(ms)", columns.avg, "right")}${padCell("Min(ms)", columns.min, "right")}${padCell("Max(ms)", columns.max, "right")}${padCell("Runs", columns.runs, "right")}`
  );
  console.log(separator);

  for (const row of rows) {
    const s = computeStats(row.samples);
    console.log(
      `${padCell(row.label, columns.case)}${padCell(s.avg.toFixed(2), columns.avg, "right")}${padCell(s.min.toFixed(2), columns.min, "right")}${padCell(s.max.toFixed(2), columns.max, "right")}${padCell(s.runs, columns.runs, "right")}`
    );
  }

  console.log(separator);
  console.log(
    `${padCell("OVERALL", columns.case)}${padCell(overall.avg.toFixed(2), columns.avg, "right")}${padCell(overall.min.toFixed(2), columns.min, "right")}${padCell(overall.max.toFixed(2), columns.max, "right")}${padCell(overall.runs, columns.runs, "right")}`
  );
}

function printImprovementTable(beforeRows, afterRows) {
  const separator = "-".repeat(80);
  const columns = {
    case: 28,
    before: 13,
    after: 12,
    delta: 12,
    speedup: 15,
  };

  console.log("\nImprovement Summary (Before vs After)");
  console.log(separator);
  console.log(
    `${padCell("Case", columns.case)}${padCell("Before(ms)", columns.before, "right")}${padCell("After(ms)", columns.after, "right")}${padCell("Delta", columns.delta, "right")}${padCell("Improvement", columns.speedup, "right")}`
  );
  console.log(separator);

  for (let i = 0; i < beforeRows.length; i += 1) {
    const beforeStats = computeStats(beforeRows[i].samples);
    const afterStats = computeStats(afterRows[i].samples);
    const delta = beforeStats.avg - afterStats.avg;
    const pct = beforeStats.avg > 0 ? (delta / beforeStats.avg) * 100 : 0;

    console.log(
      `${padCell(beforeRows[i].label, columns.case)}${padCell(beforeStats.avg.toFixed(2), columns.before, "right")}${padCell(afterStats.avg.toFixed(2), columns.after, "right")}${padCell(delta.toFixed(2), columns.delta, "right")}${padCell(`${pct.toFixed(2)}%`, columns.speedup, "right")}`
    );
  }

  console.log(separator);
}

async function createApprovedLoan(loanCore, borrower, admin, officer, idSuffix) {
  const loanId = ethers.keccak256(ethers.toUtf8Bytes(`BENCH_LOAN_${idSuffix}`));
  const productId = ethers.keccak256(ethers.toUtf8Bytes(`BENCH_PRODUCT_${idSuffix}`));

  await (
    await loanCore
      .connect(borrower)
      .createLoan(loanId, productId, ethers.parseEther("1000"), 12, 150)
  ).wait();

  await (
    await loanCore
      .connect(borrower)
      .submitLoan(loanId, 82, 1, ethers.keccak256(ethers.toUtf8Bytes(`AI_REC_${idSuffix}`)))
  ).wait();

  await (await loanCore.connect(admin).assignOfficer(loanId, officer.address)).wait();

  return loanId;
}

async function main() {
  const [admin, officer, borrower] = await ethers.getSigners();

  const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));
  const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));

  const LoanAccessControl = await ethers.getContractFactory("LoanAccessControl");
  const accessControl = await upgrades.deployProxy(LoanAccessControl, [admin.address], { kind: "uups" });
  await accessControl.waitForDeployment();

  const AuditRegistry = await ethers.getContractFactory("AuditRegistry");
  const auditRegistry = await upgrades.deployProxy(AuditRegistry, [admin.address], { kind: "uups" });
  await auditRegistry.waitForDeployment();

  const LoanCore = await ethers.getContractFactory("LoanCore");
  const loanCore = await upgrades.deployProxy(
    LoanCore,
    [await accessControl.getAddress(), await auditRegistry.getAddress(), admin.address],
    { kind: "uups" }
  );
  await loanCore.waitForDeployment();

  const Disbursement = await ethers.getContractFactory("Disbursement");
  const disbursement = await upgrades.deployProxy(
    Disbursement,
    [await loanCore.getAddress(), await auditRegistry.getAddress(), admin.address],
    { kind: "uups" }
  );
  await disbursement.waitForDeployment();

  const Repayment = await ethers.getContractFactory("Repayment");
  const repayment = await upgrades.deployProxy(
    Repayment,
    [await loanCore.getAddress(), await auditRegistry.getAddress(), admin.address],
    { kind: "uups" }
  );
  await repayment.waitForDeployment();

  await (await loanCore.setContracts(await disbursement.getAddress(), await repayment.getAddress(), ethers.ZeroAddress)).wait();

  await (await auditRegistry.grantLoggerRole(await loanCore.getAddress())).wait();
  await (await auditRegistry.grantLoggerRole(await disbursement.getAddress())).wait();
  await (await auditRegistry.grantLoggerRole(await repayment.getAddress())).wait();
  await (await auditRegistry.grantLoggerRole(admin.address)).wait();

  await (await accessControl.grantRole(SYSTEM_ROLE, admin.address)).wait();
  await (await loanCore.grantRole(SYSTEM_ROLE, admin.address)).wait();
  await (await loanCore.grantRole(LOAN_OFFICER_ROLE, officer.address)).wait();
  await (await disbursement.grantRole(LOAN_OFFICER_ROLE, officer.address)).wait();
  await (await repayment.grantRole(LOAN_OFFICER_ROLE, officer.address)).wait();

  await (
    await accessControl.registerOfficer(
      officer.address,
      ethers.keccak256(ethers.toUtf8Bytes("EMP_BENCH_001"))
    )
  ).wait();

  await (
    await accessControl.registerBorrower(
      borrower.address,
      ethers.keccak256(ethers.toUtf8Bytes("CUST_BENCH_001"))
    )
  ).wait();

  const runs = 5;

  const approvalBefore = [];
  const approvalAfter = [];
  const disbursementBefore = [];
  const disbursementAfter = [];
  const repaymentBefore = [];
  const repaymentAfter = [];
  const auditBefore = [];
  const auditAfter = [];

  for (let i = 0; i < runs; i += 1) {
    const loanId = await createApprovedLoan(loanCore, borrower, admin, officer, `APP_${i}`);

    const startBefore = process.hrtime.bigint();
    await (
      await loanCore
        .connect(officer)
        .approveLoan(loanId, ethers.parseEther("900"), ethers.keccak256(ethers.toUtf8Bytes(`NOTES_B_${i}`)))
    ).wait();
    await (
      await auditRegistry.connect(admin).log(
        loanId,
        "loan",
        0,
        ethers.keccak256(ethers.toUtf8Bytes(`EXTRA_APPROVAL_B_${i}`)),
        ethers.ZeroHash,
        ethers.keccak256(ethers.toUtf8Bytes(`EXTRA_APPROVAL_B_STATE_${i}`))
      )
    ).wait();
    const endBefore = process.hrtime.bigint();
    approvalBefore.push(toMs(startBefore, endBefore));
  }

  for (let i = 0; i < runs; i += 1) {
    const loanId = await createApprovedLoan(loanCore, borrower, admin, officer, `APP_OPT_${i}`);

    const startAfter = process.hrtime.bigint();
    await (
      await loanCore
        .connect(officer)
        .approveLoan(loanId, ethers.parseEther("900"), ethers.keccak256(ethers.toUtf8Bytes(`NOTES_A_${i}`)))
    ).wait();
    const endAfter = process.hrtime.bigint();
    approvalAfter.push(toMs(startAfter, endAfter));
  }

  for (let i = 0; i < runs; i += 1) {
    const loanId = await createApprovedLoan(loanCore, borrower, admin, officer, `DISB_${i}`);
    await (
      await loanCore
        .connect(officer)
        .approveLoan(loanId, ethers.parseEther("900"), ethers.keccak256(ethers.toUtf8Bytes(`DISB_NOTES_B_${i}`)))
    ).wait();

    const startBefore = process.hrtime.bigint();
    await (
      await disbursement.connect(officer).initiateDisbursement(loanId, ethers.parseEther("900"), 1)
    ).wait();
    const disbursementId = await disbursement.loanToDisbursement(loanId);
    await (
      await disbursement
        .connect(officer)
        .completeDisbursement(disbursementId, ethers.keccak256(ethers.toUtf8Bytes(`DISB_REF_B_${i}`)))
    ).wait();
    await (
      await auditRegistry.connect(admin).log(
        disbursementId,
        "disbursement",
        5,
        ethers.keccak256(ethers.toUtf8Bytes(`EXTRA_DISB_B_${i}`)),
        ethers.ZeroHash,
        ethers.keccak256(ethers.toUtf8Bytes(`EXTRA_DISB_B_STATE_${i}`))
      )
    ).wait();
    const endBefore = process.hrtime.bigint();
    disbursementBefore.push(toMs(startBefore, endBefore));
  }

  for (let i = 0; i < runs; i += 1) {
    const loanId = await createApprovedLoan(loanCore, borrower, admin, officer, `DISB_OPT_${i}`);
    await (
      await loanCore
        .connect(officer)
        .approveLoan(loanId, ethers.parseEther("900"), ethers.keccak256(ethers.toUtf8Bytes(`DISB_NOTES_A_${i}`)))
    ).wait();

    const startAfter = process.hrtime.bigint();
    await (
      await disbursement.connect(officer).initiateDisbursement(loanId, ethers.parseEther("900"), 1)
    ).wait();
    const disbursementId = await disbursement.loanToDisbursement(loanId);
    await (
      await disbursement
        .connect(officer)
        .completeDisbursement(disbursementId, ethers.keccak256(ethers.toUtf8Bytes(`DISB_REF_A_${i}`)))
    ).wait();
    const endAfter = process.hrtime.bigint();
    disbursementAfter.push(toMs(startAfter, endAfter));
  }

  for (let i = 0; i < runs; i += 1) {
    const loanId = await createApprovedLoan(loanCore, borrower, admin, officer, `PAY_${i}`);
    await (
      await loanCore
        .connect(officer)
        .approveLoan(loanId, ethers.parseEther("900"), ethers.keccak256(ethers.toUtf8Bytes(`PAY_NOTES_B_${i}`)))
    ).wait();
    await (await loanCore.connect(admin).markDisbursed(loanId, ethers.parseEther("900"))).wait();
    await (
      await repayment
        .connect(admin)
        .createSchedule(loanId, borrower.address, ethers.parseEther("900"), 150, 12, Math.floor(Date.now() / 1000))
    ).wait();

    const startBefore = process.hrtime.bigint();
    await (
      await repayment
        .connect(officer)
        .recordPayment(
          loanId,
          1,
          ethers.parseEther("80"),
          0,
          ethers.keccak256(ethers.toUtf8Bytes(`PAY_REF_B_${i}`))
        )
    ).wait();
    await (
      await auditRegistry.connect(admin).log(
        ethers.keccak256(ethers.toUtf8Bytes(`PAY_EXTRA_RESOURCE_${i}`)),
        "payment",
        7,
        ethers.keccak256(ethers.toUtf8Bytes(`EXTRA_PAY_B_${i}`)),
        ethers.ZeroHash,
        ethers.keccak256(ethers.toUtf8Bytes(`EXTRA_PAY_B_STATE_${i}`))
      )
    ).wait();
    const endBefore = process.hrtime.bigint();
    repaymentBefore.push(toMs(startBefore, endBefore));
  }

  for (let i = 0; i < runs; i += 1) {
    const loanId = await createApprovedLoan(loanCore, borrower, admin, officer, `PAY_OPT_${i}`);
    await (
      await loanCore
        .connect(officer)
        .approveLoan(loanId, ethers.parseEther("900"), ethers.keccak256(ethers.toUtf8Bytes(`PAY_NOTES_A_${i}`)))
    ).wait();
    await (await loanCore.connect(admin).markDisbursed(loanId, ethers.parseEther("900"))).wait();
    await (
      await repayment
        .connect(admin)
        .createSchedule(loanId, borrower.address, ethers.parseEther("900"), 150, 12, Math.floor(Date.now() / 1000))
    ).wait();

    const startAfter = process.hrtime.bigint();
    await (
      await repayment
        .connect(officer)
        .recordPayment(
          loanId,
          1,
          ethers.parseEther("80"),
          0,
          ethers.keccak256(ethers.toUtf8Bytes(`PAY_REF_A_${i}`))
        )
    ).wait();
    const endAfter = process.hrtime.bigint();
    repaymentAfter.push(toMs(startAfter, endAfter));
  }

  for (let i = 0; i < runs; i += 1) {
    const start = process.hrtime.bigint();
    await (
      await auditRegistry.connect(admin).log(
        ethers.keccak256(ethers.toUtf8Bytes(`RES_SINGLE_${i}`)),
        "loan",
        0,
        ethers.keccak256(ethers.toUtf8Bytes(`DATA_SINGLE_${i}`)),
        ethers.ZeroHash,
        ethers.keccak256(ethers.toUtf8Bytes(`STATE_SINGLE_${i}`))
      )
    ).wait();
    const end = process.hrtime.bigint();
    auditBefore.push(toMs(start, end));
  }

  for (let run = 0; run < runs; run += 1) {
    const ids = [];
    const types = [];
    const actions = [];
    const details = [];
    const prev = [];
    const next = [];

    for (let i = 0; i < 5; i += 1) {
      ids.push(ethers.keccak256(ethers.toUtf8Bytes(`RES_BATCH_${run}_${i}`)));
      types.push("loan");
      actions.push(0);
      details.push(ethers.keccak256(ethers.toUtf8Bytes(`DATA_BATCH_${run}_${i}`)));
      prev.push(ethers.ZeroHash);
      next.push(ethers.keccak256(ethers.toUtf8Bytes(`STATE_BATCH_${run}_${i}`)));
    }

    const start = process.hrtime.bigint();
    await (await auditRegistry.connect(admin).logBatch(ids, types, actions, details, prev, next)).wait();
    const end = process.hrtime.bigint();

    auditAfter.push(toMs(start, end) / ids.length);
  }

  const beforeRows = [
    { label: "Loan approval", samples: approvalBefore },
    { label: "Disbursement flow", samples: disbursementBefore },
    { label: "Repayment recording", samples: repaymentBefore },
    { label: "Audit logging", samples: auditBefore },
  ];

  const afterRows = [
    { label: "Loan approval", samples: approvalAfter },
    { label: "Disbursement flow", samples: disbursementAfter },
    { label: "Repayment recording", samples: repaymentAfter },
    { label: "Audit logging", samples: auditAfter },
  ];

  printLatencyTable("BEFORE Performance Table (Baseline)", beforeRows);
  printLatencyTable("AFTER Performance Table (Optimized)", afterRows);
  printImprovementTable(beforeRows, afterRows);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
