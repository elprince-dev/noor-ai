import * as lambda from 'aws-cdk-lib/aws-lambda';
import { execSync } from 'child_process';
import * as path from 'path';

// Target the Lambda runtime, not the host interpreter, so the right wheels
// are resolved and installed. manylinux_2_28 (glibc 2.28) is compatible with
// the Lambda Python 3.12 runtime (Amazon Linux 2023, glibc 2.34).
const PYTHON_VERSION = '3.12';
const PYTHON_PLATFORM = 'x86_64-manylinux_2_28';

/**
 * Builds a Lambda `Code` asset for a `uv`-managed Python project, bundling
 * dependencies on the host — no Docker.
 *
 * CDK calls `local.tryBundle()` first; because it succeeds (or throws), the
 * Docker fallback image is never used. Dependencies are resolved from the
 * project's `pyproject.toml` and installed as Lambda-compatible wheels.
 *
 * @param projectDir Absolute path to the backend project (holds pyproject.toml).
 * @param appPaths   Files/dirs (relative to projectDir) copied to the zip root,
 *                   e.g. the source package and the handler entry file.
 */
export function pythonLambdaCode(projectDir: string, appPaths: string[]): lambda.Code {
  return lambda.Code.fromAsset(projectDir, {
    bundling: {
      // Required by the type, but only reached if local bundling returns
      // false. tryBundle throws instead, so Docker is never invoked.
      image: lambda.Runtime.PYTHON_3_12.bundlingImage,
      local: {
        tryBundle(outputDir: string): boolean {
          assertUvInstalled();
          installDependencies(projectDir, outputDir);
          copyAppFiles(projectDir, outputDir, appPaths);
          return true;
        },
      },
    },
  });
}

function assertUvInstalled(): void {
  try {
    execSync('uv --version', { stdio: 'ignore' });
  } catch {
    throw new Error(
      'uv is required to bundle the Lambda without Docker. ' +
        'Install it from https://docs.astral.sh/uv/getting-started/installation/'
    );
  }
}

function installDependencies(projectDir: string, outputDir: string): void {
  const pyproject = path.join(projectDir, 'pyproject.toml');
  const requirements = path.join(outputDir, 'requirements.txt');
  const platform = `--python-platform ${PYTHON_PLATFORM} --python-version ${PYTHON_VERSION}`;

  run([
    `uv pip compile "${pyproject}" --quiet ${platform} -o "${requirements}"`,
    `uv pip install -r "${requirements}" --target "${outputDir}" ${platform} --only-binary :all:`,
    `rm -f "${requirements}"`,
  ]);
}

function copyAppFiles(projectDir: string, outputDir: string, appPaths: string[]): void {
  run(appPaths.map((p) => `cp -r "${path.join(projectDir, p)}" "${outputDir}/"`));
}

function run(commands: string[]): void {
  execSync(commands.join(' && '), { stdio: 'inherit' });
}
